"""Live model/tool compatibility checks in deployed container; synthetic work only."""
import asyncio,json,tempfile,os
from claude_agent_sdk import ClaudeSDKClient,ClaudeAgentOptions,AssistantMessage,ResultMessage,ToolUseBlock,TextBlock
from synapsis.agents.definitions import SUBAGENTS

async def check(model,delegate=False):
 with tempfile.TemporaryDirectory(prefix='ia-model-qa-') as cwd:
  options=ClaudeAgentOptions(model=model,cwd=cwd,permission_mode='bypassPermissions',
   allowed_tools=['Bash','Task','Agent'] if delegate else ['Bash'],
   system_prompt='You are performing a synthetic release test. Follow the exact short task. Do not read files or access network.',
   setting_sources=[],max_turns=5,max_budget_usd=1.0,
   agents={'data_analysis':SUBAGENTS['data_analysis']} if delegate else None)
  prompt='Use Bash to calculate 17 * 19 and reply with the number.'
  if delegate:prompt='Delegate to the data_analysis specialist to calculate 17 * 19 using Bash. Return its number. Do not calculate yourself.'
  seen=[];texts=[];result=None;models=[]
  async with ClaudeSDKClient(options=options) as client:
   await client.query(prompt)
   async for message in client.receive_response():
    if isinstance(message,AssistantMessage):
     models.append(message.model)
     for block in message.content:
      if isinstance(block,ToolUseBlock):seen.append(block.name)
      if isinstance(block,TextBlock):texts.append(block.text)
    if isinstance(message,ResultMessage):result=message
  assert result and not result.is_error,(model,'SDK result failed')
  assert '323' in '\n'.join(texts),(model,'wrong arithmetic')
  assert any(t in ('Task','Agent') for t in seen) if delegate else 'Bash' in seen,(model,'required tool not used')
  assert model in models,(model,'requested model not observed',models)
  return {'requested':model,'observed_models':sorted(set(models)),'tools':seen,'delegated':delegate,'cost_usd':result.total_cost_usd,'result':'passed'}

async def main():
 results=[]
 for model in ('claude-sonnet-5','claude-opus-5','claude-fable-5-1'):
  results.append(await asyncio.wait_for(check(model),180))
 results.append(await asyncio.wait_for(check('claude-sonnet-5',True),180))
 print(json.dumps({'live_model_checks':results}))
asyncio.run(main())

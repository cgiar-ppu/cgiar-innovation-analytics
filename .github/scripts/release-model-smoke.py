"""Live model/tool compatibility checks in the deployed container; synthetic work only.

Purpose (unchanged): prove that every selectable model answers WITH A TOOL CALL
through the deployed CLI, and that orchestrator -> specialist delegation works.

Since the 2026-09-26 agent sandbox the IA agent has no Bash (or any shell); its
tools are the app's own MCP tools. The checks therefore use the IA tool
``prms_query`` from the app's in-process MCP server (``synapsis.tools.synapsis_mcp``)
with a synthetic ``SELECT 17 * 19`` -- not an innovation count -- and delegate to
the ``prms_data_analyst`` specialist, which carries ``prms_query``. No built-in
tool is offered except ``Task`` for the delegation check.
"""
import asyncio,json,tempfile
from claude_agent_sdk import ClaudeSDKClient,ClaudeAgentOptions,AssistantMessage,ResultMessage,ToolUseBlock,TextBlock
from synapsis.agents.definitions import SUBAGENTS
from synapsis.tools import synapsis_mcp

TOOL='mcp__synapsis__prms_query'
SPECIALIST='prms_data_analyst'
SQL='SELECT 17 * 19 AS qa_product'

def options(model,cwd,delegate=False):
 return ClaudeAgentOptions(model=model,cwd=cwd,permission_mode='bypassPermissions',
  tools=['Task'] if delegate else [],
  allowed_tools=[TOOL,'Task','Agent'] if delegate else [TOOL],
  mcp_servers={'synapsis':synapsis_mcp},strict_mcp_config=True,
  system_prompt='You are performing a synthetic release test. Follow the exact short task. Do not read files or access the network.',
  setting_sources=[],max_turns=6,max_budget_usd=1.0,
  agents={SPECIALIST:SUBAGENTS[SPECIALIST]} if delegate else None)

def prompt(delegate=False):
 if delegate:
  return (f'Delegate to the {SPECIALIST} specialist: it must run `{SQL}` with its prms_query tool and return the number. '
          'This is synthetic arithmetic, not an innovation count. Return its number. Do not calculate or query yourself.')
 return f'Use the prms_query tool to run `{SQL}` and reply with the number. This is synthetic arithmetic, not an innovation count.'

async def check(model,delegate=False):
 with tempfile.TemporaryDirectory(prefix='ia-model-qa-') as cwd:
  seen=[];texts=[];result=None;models=[]
  async with ClaudeSDKClient(options=options(model,cwd,delegate)) as client:
   await client.query(prompt(delegate))
   async for message in client.receive_response():
    if isinstance(message,AssistantMessage):
     models.append(message.model)
     for block in message.content:
      if isinstance(block,ToolUseBlock):seen.append(block.name)
      if isinstance(block,TextBlock):texts.append(block.text)
    if isinstance(message,ResultMessage):result=message
  assert result and not result.is_error,(model,'SDK result failed')
  assert '323' in '\n'.join(texts),(model,'wrong arithmetic')
  assert any(t in ('Task','Agent') for t in seen) if delegate else TOOL in seen,(model,'required tool not used',seen)
  assert model in models,(model,'requested model not observed',models)
  return {'requested':model,'observed_models':sorted(set(models)),'tools':seen,'delegated':delegate,
          'specialist_tool_seen':TOOL in seen if delegate else None,'cost_usd':result.total_cost_usd,'result':'passed'}

async def main():
 results=[]
 for model in ('claude-sonnet-5','claude-opus-5','claude-fable-5-1'):
  results.append(await asyncio.wait_for(check(model),180))
 results.append(await asyncio.wait_for(check('claude-sonnet-5',True),240))
 print(json.dumps({'live_model_checks':results}))

# run-release-smoke.py execs this file inside `python -c` (__name__ == '__main__'); tests import it.
if __name__=='__main__':asyncio.run(main())

"""Current model selection and specialist export requirements."""
import pytest
from synapsis.constants import SELECTABLE_MODEL_IDS, DEFAULT_MODEL
from synapsis.agents.definitions import SUBAGENTS
from synapsis.agents.loader import current_agent_model, load_all_agents
from synapsis.exporters.watermark import WATERMARK_BANNER
from synapsis.system_prompt import build_system_prompt
from synapsis.validators.agents import validate_model

@pytest.mark.parametrize('model',['claude-sonnet-5','claude-opus-5-5','claude-opus-5','claude-fable-5-1'])
def test_requested_model_is_selectable_and_valid_for_custom_agent(model):
 assert model in SELECTABLE_MODEL_IDS
 validate_model(model)

def test_specialists_use_explicit_current_sonnet_without_alias_drift():
 assert DEFAULT_MODEL=='claude-sonnet-5'
 assert {a.model for a in SUBAGENTS.values()}=={'claude-sonnet-5'}
 assert current_agent_model('sonnet')=='claude-sonnet-5'
 assert current_agent_model('opus')=='claude-opus-5'
 assert current_agent_model('claude-fable-5-1')=='claude-fable-5-1'
 assert current_agent_model(None)=='claude-sonnet-5'

@pytest.mark.asyncio
async def test_loaded_custom_and_builtin_agents_preserve_export_policy(initialized_db):
 from synapsis.database import get_db
 import time
 async with get_db() as db:
  await db.execute('INSERT INTO agents(id,name,description,system_prompt,tools,model,type,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',('release_custom','Custom','Test','Original prompt','[]','opus','custom',1,time.time(),time.time()))
  await db.commit()
 agents=await load_all_agents()
 assert agents['release_custom'].model=='claude-opus-5'
 assert agents['release_custom'].prompt.startswith('Original prompt')
 assert all(WATERMARK_BANNER in a.prompt for a in agents.values())
 assert WATERMARK_BANNER in build_system_prompt(agents)
 # Loading does not mutate definitions and append repeated instructions.
 assert all(a.prompt.count(WATERMARK_BANNER)==1 for a in SUBAGENTS.values())
 assert all(a.prompt.count(WATERMARK_BANNER)==1 for a in (await load_all_agents()).values())

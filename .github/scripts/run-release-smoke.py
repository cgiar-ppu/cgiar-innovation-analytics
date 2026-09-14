import boto3,base64,os,shlex,time,json
from pathlib import Path
account=os.environ['EXPECTED_ACCOUNT'];assert boto3.client('sts').get_caller_identity()['Account']==account
stage=os.environ['STAGE'];cf=boto3.client('cloudformation');ssm=boto3.client('ssm')
stack=cf.describe_stacks(StackName='cgiar-ia-'+stage)['Stacks'][0]
instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='InstanceId')
request=json.loads(Path('.github/smoke-request.json').read_text())
script=('.github/scripts/release-chat-smoke.py' if request.get('chat') else
        '.github/scripts/release-model-smoke.py' if request.get('models') else '.github/scripts/release-smoke.py')
scripts=['.github/scripts/release-file-integrity.py'] if request.get('integrity') else [script]
if request.get('all'):
 scripts=['.github/scripts/release-model-smoke.py','.github/scripts/release-chat-smoke.py','.github/scripts/release-smoke.py']
commands=['set -e']
for script in scripts:
 encoded=base64.b64encode(Path(script).read_bytes()).decode()
 prefix='python3 -c ' if request.get('integrity') else 'docker exec cgiar-innovation-analytics python -c '
 commands.append(prefix+shlex.quote('import base64;exec(base64.b64decode('+repr(encoded)+'))'))
command='\n'.join(commands)
cid=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=900)['Command']['CommandId']
for _ in range(180):
 try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=instance)
 except ssm.exceptions.InvocationDoesNotExist:time.sleep(5);continue
 if r['Status']=='Success':print(r['StandardOutputContent']);break
 if r['Status'] in ('Failed','Cancelled','TimedOut'):
  print(r['StandardOutputContent']);print(r['StandardErrorContent']);raise RuntimeError('Smoke failed '+cid)
 time.sleep(5)
else:raise TimeoutError(cid)

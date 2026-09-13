import boto3,base64,os,shlex,time,json
from pathlib import Path
account=os.environ['EXPECTED_ACCOUNT'];assert boto3.client('sts').get_caller_identity()['Account']==account
stage=os.environ['STAGE'];cf=boto3.client('cloudformation');ssm=boto3.client('ssm')
stack=cf.describe_stacks(StackName='cgiar-ia-'+stage)['Stacks'][0]
instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='InstanceId')
request=json.loads(Path('.github/smoke-request.json').read_text())
script='.github/scripts/release-model-smoke.py' if request.get('models') else '.github/scripts/release-smoke.py'
encoded=base64.b64encode(Path(script).read_bytes()).decode()
command='docker exec cgiar-innovation-analytics python -c '+shlex.quote('import base64;exec(base64.b64decode('+repr(encoded)+'))')
cid=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=900)['Command']['CommandId']
for _ in range(180):
 try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=instance)
 except ssm.exceptions.InvocationDoesNotExist:time.sleep(5);continue
 if r['Status']=='Success':print(r['StandardOutputContent']);break
 if r['Status'] in ('Failed','Cancelled','TimedOut'):
  print(r['StandardOutputContent']);print(r['StandardErrorContent']);raise RuntimeError('Smoke failed '+cid)
 time.sleep(5)
else:raise TimeoutError(cid)

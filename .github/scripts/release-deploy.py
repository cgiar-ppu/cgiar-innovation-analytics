"""CI-only deployment; preserves existing infra and supplies target-only secrets."""
import boto3,json,os,secrets,subprocess,base64,shlex,time
from pathlib import Path
stage=os.environ['STAGE'];account=os.environ['EXPECTED_ACCOUNT'];region='eu-central-1'
assert boto3.client('sts').get_caller_identity()['Account']==account
cf=boto3.client('cloudformation',region_name=region);ssm=boto3.client('ssm',region_name=region);s3=boto3.client('s3',region_name=region)
bucket='cgiar-ia-artifacts-'+account
try:s3.head_bucket(Bucket=bucket)
except Exception:
 assert stage=='staging','Existing artifacts bucket inaccessible'
 s3.create_bucket(Bucket=bucket,CreateBucketConfiguration={'LocationConstraint':region})
 s3.put_public_access_block(Bucket=bucket,PublicAccessBlockConfiguration={k:True for k in ('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')})
 s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={'Status':'Enabled'})
for key,value in [('anthropic-api-key',os.environ['RELEASE_ANTHROPIC_KEY']),('openai-api-key',os.environ.get('RELEASE_OPENAI_KEY','')),('jwt-secret',secrets.token_hex(32))]:
 name=f'/cgiar-ia-{stage}/{key}'
 try:r=ssm.get_parameter(Name=name,WithDecryption=True);exists=bool(r['Parameter']['Value'])
 except ssm.exceptions.ParameterNotFound:exists=False
 if not exists and value:ssm.put_parameter(Name=name,Type='SecureString',Value=value,Overwrite=True)
name='cgiar-ia-'+stage
try:stack=cf.describe_stacks(StackName=name)['Stacks'][0]
except cf.exceptions.ClientError as e:
 assert stage=='staging' and 'does not exist' in str(e)
 subprocess.run(['aws','cloudformation','deploy','--stack-name',name,'--template-file','infra/staging-release.yaml','--capabilities','CAPABILITY_NAMED_IAM','--parameter-overrides','Stage=staging','InstanceType=t3.large','VpcId='+os.environ['VPC_ID'],'SubnetId1='+os.environ['SUBNET_ID_1'],'SubnetId2='+os.environ['SUBNET_ID_2'],'AcmCertificateArn='+os.environ['ACM_CERTIFICATE_ARN']],check=True)
 stack=cf.describe_stacks(StackName=name)['Stacks'][0]
assert stack['StackStatus'] in ('CREATE_COMPLETE','UPDATE_COMPLETE')
outputs={x['OutputKey']:x['OutputValue'] for x in stack['Outputs']};instance=outputs['InstanceId']
for _ in range(90):
 info=ssm.describe_instance_information(Filters=[{'Key':'InstanceIds','Values':[instance]}])['InstanceInformationList']
 if info and info[0]['PingStatus']=='Online':break
 time.sleep(5)
else:raise TimeoutError('SSM unavailable; instance not rebooted automatically')
config={'stage':stage,'account':account,'sha':os.environ['SOURCE_SHA'],'issuer':os.environ['SSO_ISSUER'],'client':os.environ['SSO_CLIENT'],'domain':os.environ['SSO_DOMAIN'],'origin':os.environ['SSO_ORIGIN'],'admins':os.environ['SSO_ADMINS']}
request=json.loads(Path('.github/promotion-request.json').read_text())
config.update(request.get('models_config',{}))
script=base64.b64encode(Path('.github/scripts/release-host.py').read_bytes()).decode()
command='set -e\nsystemctl enable --now docker\npython3 -c '+shlex.quote('import base64;exec(base64.b64decode('+repr(script)+'))')+' '+shlex.quote(json.dumps(config))
cid=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=900)['Command']['CommandId']
for _ in range(180):
 try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=instance)
 except ssm.exceptions.InvocationDoesNotExist:time.sleep(5);continue
 if r['Status']=='Success':print(r['StandardOutputContent']);break
 if r['Status'] in ('Failed','Cancelled','TimedOut'):
  print(r['StandardOutputContent']);print(r['StandardErrorContent']);raise RuntimeError('Deploy failed '+cid)
 time.sleep(5)
else:raise TimeoutError(cid)
print(json.dumps(outputs))

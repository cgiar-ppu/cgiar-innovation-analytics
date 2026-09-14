"""Disable automatic restart on stopped rollback containers; current app is untouched."""
import boto3,os,json,shlex,time
account=os.environ['EXPECTED_ACCOUNT'];assert boto3.client('sts').get_caller_identity()['Account']==account
stage=os.environ['STAGE'];stack=boto3.client('cloudformation').describe_stacks(StackName='cgiar-ia-'+stage)['Stacks'][0]
instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='InstanceId')
code='''import subprocess as sp,json
names=sp.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
retained=[n for n in names if n.startswith('cgiar-innovation-analytics-before-')]
for name in retained:
 item=json.loads(sp.check_output(['docker','inspect',name],text=True))[0]
 assert not item['State']['Running'],'Unexpected running rollback container'
 sp.run(['docker','update','--restart=no',name],check=True,stdout=sp.DEVNULL)
 item=json.loads(sp.check_output(['docker','inspect',name],text=True))[0]
 assert item['HostConfig']['RestartPolicy']['Name']=='no'
active=json.loads(sp.check_output(['docker','inspect','cgiar-innovation-analytics'],text=True))[0]
assert active['State']['Running'] and active['HostConfig']['RestartPolicy']['Name']=='always'
print(json.dumps({'retained_containers':len(retained),'retained_restart':'no','active_app':'running','active_restart':'always'}))
'''
ssm=boto3.client('ssm');cid=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':['python3 -c '+shlex.quote(code)]},TimeoutSeconds=60)['Command']['CommandId']
for _ in range(30):
 try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=instance)
 except ssm.exceptions.InvocationDoesNotExist:time.sleep(2);continue
 if r['Status']=='Success':print(r['StandardOutputContent']);break
 if r['Status'] in ('Failed','TimedOut','Cancelled'):raise RuntimeError('Retention check failed: '+cid)
 time.sleep(2)
else:raise TimeoutError(cid)

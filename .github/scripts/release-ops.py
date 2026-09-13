"""Bounded first-release bootstrap; run only through GitHub Actions OIDC."""
import boto3, json, os, time, shlex
from pathlib import Path
region='eu-central-1'
account=boto3.client('sts').get_caller_identity()['Account']
operation=os.environ['OPERATION']
if operation=='identity':
 assert account=='972793825893'
 cf=boto3.client('cloudformation',region_name=region)
 resources={}
 for stage in ('staging','prod'):
  origin='https://innovation-analytics'+('-staging' if stage=='staging' else '')+'.synapsis-analytics.com'
  resources[stage.title()+'Client']={'Type':'AWS::Cognito::UserPoolClient','Properties':{
   'ClientName':'cgiar-ia-'+stage+'-web','UserPoolId':'eu-central-1_QDmB1qeBE',
   'GenerateSecret':False,'AllowedOAuthFlowsUserPoolClient':True,'AllowedOAuthFlows':['code'],
   'AllowedOAuthScopes':['openid','email','profile'],'CallbackURLs':[origin+'/auth/callback'],
   'LogoutURLs':[origin],'SupportedIdentityProviders':['AzureAD'],
   'ReadAttributes':['email','name','email_verified'],'WriteAttributes':['email','name'],
   'EnableTokenRevocation':True,'PreventUserExistenceErrors':'ENABLED',
   'AccessTokenValidity':60,'IdTokenValidity':60,'RefreshTokenValidity':1,
   'TokenValidityUnits':{'AccessToken':'minutes','IdToken':'minutes','RefreshToken':'days'}}}
 template={'AWSTemplateFormatVersion':'2010-09-09','Description':'IA deliberately shared CGIAR federation; separate staging and production clients.',
 'Resources':resources,'Outputs':{key:{'Value':{'Ref':key}} for key in resources}}
 name='cgiar-ia-release-identity'
 try:
  cf.describe_stacks(StackName=name)
  try:
   cf.update_stack(StackName=name,TemplateBody=json.dumps(template)); waiter='stack_update_complete'
  except cf.exceptions.ClientError as e:
   if 'No updates' not in str(e): raise
   waiter=None
 except cf.exceptions.ClientError as e:
  if 'does not exist' not in str(e): raise
  cf.create_stack(StackName=name,TemplateBody=json.dumps(template),Tags=[{'Key':'Project','Value':'cgiar-innovation-analytics'}]); waiter='stack_create_complete'
 if waiter: cf.get_waiter(waiter).wait(StackName=name)
 print(json.dumps(cf.describe_stacks(StackName=name)['Stacks'][0]['Outputs']))
elif operation=='certificate':
 assert account=='053142643230'
 acm=boto3.client('acm',region_name=region); domain='innovation-analytics-staging.synapsis-analytics.com'
 matches=[x for page in acm.get_paginator('list_certificates').paginate() for x in page['CertificateSummaryList'] if x['DomainName']==domain]
 arn=matches[0]['CertificateArn'] if matches else acm.request_certificate(DomainName=domain,ValidationMethod='DNS',IdempotencyToken='iarelease20260914',Tags=[{'Key':'Project','Value':'cgiar-innovation-analytics'}])['CertificateArn']
 for _ in range(20):
  cert=acm.describe_certificate(CertificateArn=arn)['Certificate']
  records=[x.get('ResourceRecord') for x in cert.get('DomainValidationOptions',[]) if x.get('ResourceRecord')]
  if records: break
  time.sleep(3)
 print(json.dumps({'arn':arn,'records':records,'status':cert['Status']}))
elif operation=='inspect':
 assert account=='207258148366'
 ssm=boto3.client('ssm',region_name=region)
 # Metadata only: no env values, credentials, user messages or titles.
 code="""import json,subprocess,sqlite3,os
x=json.loads(subprocess.check_output(['docker','inspect','cgiar-innovation-analytics']))[0]
print(json.dumps({'image':x['Config']['Image'],'mounts':x['Mounts'],'env_names':[e.split('=',1)[0] for e in x['Config']['Env']]}))
"""
 command='python3 -c '+shlex.quote(code)
 cid=ssm.send_command(InstanceIds=['i-0f2866b0c6903a70e'],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=60)['Command']['CommandId']
 for _ in range(40):
  try: r=ssm.get_command_invocation(CommandId=cid,InstanceId='i-0f2866b0c6903a70e')
  except ssm.exceptions.InvocationDoesNotExist: time.sleep(2);continue
  if r['Status']=='Success': print(r['StandardOutputContent']);break
  if r['Status'] in ('Failed','Cancelled','TimedOut'): raise RuntimeError('Inspection failed: '+cid)
  time.sleep(2)
 else: raise TimeoutError(cid)
else: raise ValueError(operation)

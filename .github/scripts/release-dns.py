import boto3,json
from pathlib import Path
assert boto3.client('sts').get_caller_identity()['Account']=='919959486181'
request=json.loads(Path('.github/dns-request.json').read_text())
for change in request['Changes']:
 record=change['ResourceRecordSet']
 assert 'innovation-analytics' in record['Name'] and record['Name'].endswith('.synapsis-analytics.com.')
 assert change['Action'] in ('UPSERT','DELETE','CREATE')
client=boto3.client('route53')
r=client.change_resource_record_sets(HostedZoneId='Z079841559W4HJ5A3Q2Y',ChangeBatch=request)
client.get_waiter('resource_record_sets_changed').wait(Id=r['ChangeInfo']['Id'])
print('Verified requested IA DNS change is INSYNC')

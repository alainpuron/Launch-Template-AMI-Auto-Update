import boto3
import json

launch_template_tag = 'AMI_Template_Update'

def lambda_handler(event, context):
    ec2 = boto3.client('ec2')

    # Get instances with the tag AMI_DailyUpdate=True
    response = ec2.describe_instances(
        Filters=[{'Name': 'tag:AMI_DailyUpdate', 'Values': ['True']}]
    )

    # Paginate in case of more instances
    instances = []
    while True:
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                print(f"Found instance with ID: {instance_id}")

                if 'Tags' in instance:
                    tags = {tag['Key']: tag['Value'] for tag in instance['Tags']}
                    print(f"Tags found: {tags}")
                else:
                    print(f"No 'Tags' found for instance {instance_id}.")
                    continue

                instances.append(instance)

        if 'NextToken' in response:
            response = ec2.describe_instances(
                Filters=[{'Name': 'tag:AMI_DailyUpdate', 'Values': ['True']}],
                NextToken=response['NextToken']
            )
        else:
            break

    # Describe AMIs with tag AMI_DailyUpdate=True
    ami_response = ec2.describe_images(
        Filters=[{'Name': 'tag:AMI_DailyUpdate', 'Values': ['True']}, {'Name': 'state', 'Values': ['available']}],
        Owners=['self']
    )

    print(f"Found {len(ami_response['Images'])} AMIs with tag AMI_DailyUpdate=True")

    if not ami_response['Images']:
        print("No AMIs found. Exiting.")
        return {'statusCode': 200, 'body': 'No AMIs found.'}

    # Loop through all AMIs and print details
    for image in ami_response['Images']:
        print(f"AMI ID: {image['ImageId']}")
        print(f"AMI Name: {image['Name']}")
        print(f"State: {image['State']}")
        print(f"Creation Date: {image['CreationDate']}")

        # Extract instance-id from the AMI's tags
        tags = image.get('Tags', [])
        source_instance_id = next((tag['Value'] for tag in tags if tag['Key'] == 'instance-id'), None)

        if source_instance_id:
            print(f"Source Instance ID from AMI tag: {source_instance_id}")
        else:
            print("No 'instance-id' tag found for this AMI.")

    # Get the latest AMI
    latest_ami = sorted(ami_response['Images'], key=lambda x: x['CreationDate'], reverse=True)[0]
    latest_ami_id = latest_ami['ImageId']
    print(f"Latest AMI ID: {latest_ami_id}")

    # Get instance-id from latest AMI's tags
    latest_ami_tags = latest_ami.get('Tags', [])
    latest_ami_instance_id = next(
        (tag['Value'] for tag in latest_ami_tags if tag['Key'] == 'instance-id'),
        None
    )

    print(f"Source Instance ID of latest AMI: {latest_ami_instance_id}")

    # Find matching launch templates
    matching_templates = get_launch_templates_by_tag(launch_template_tag, 'True')

    print(f"Found launch templates: {matching_templates}")

    # Update launch templates with the latest AMI
    all_amis = ami_response['Images']
    update_all_templates_with_matching_ami(all_amis)

    return {
        'statusCode': 200,
        'body': 'Launch templates updated successfully!'
    }


def get_launch_templates_by_tag(tag_key, tag_value):
    ec2 = boto3.client('ec2')

    response = ec2.describe_launch_templates()
    matching_templates = []

    for template in response['LaunchTemplates']:
        launch_template_id = template['LaunchTemplateId']
        print(f"Checking Launch Template ID: {launch_template_id}")

        tags = template.get('Tags', [])
        print(f"Tags for Launch Template {launch_template_id}: {tags}")

        for tag in tags:
            if tag['Key'] == tag_key and tag['Value'] == tag_value:
                matching_templates.append(launch_template_id)
                print(f"Launch Template {launch_template_id} has the tag {tag_key}={tag_value}")
                break

    return matching_templates


def update_all_templates_with_matching_ami(all_amis):
    ec2 = boto3.client('ec2')

    matching_templates = get_launch_templates_by_tag(launch_template_tag, 'True')

    for template_id in matching_templates:
        print(f"Processing launch template: {template_id}")

        versions = ec2.describe_launch_template_versions(
            LaunchTemplateId=template_id,
            Versions=['$Latest']
        )

        if not versions['LaunchTemplateVersions']:
            print(f"No versions found for launch template {template_id}")
            continue

        latest_version_data = versions['LaunchTemplateVersions'][0]['LaunchTemplateData']
        current_ami_id = latest_version_data.get('ImageId')

        if not current_ami_id:
            print(f"No AMI found in launch template {template_id}")
            continue

        # Get instance-id from the current AMI's tags
        current_ami_info = ec2.describe_images(ImageIds=[current_ami_id])['Images'][0]
        tags = current_ami_info.get('Tags', [])
        source_instance_id = next((tag['Value'] for tag in tags if tag['Key'] == 'instance-id'), None)

        if not source_instance_id:
            print(f"No 'instance-id' tag found for AMI {current_ami_id}")
            continue

        # Filter AMIs that match this instance-id
        matching_amis = [
            ami for ami in all_amis
            if any(tag['Key'] == 'instance-id' and tag['Value'] == source_instance_id for tag in ami.get('Tags', []))
        ]

        if not matching_amis:
            print(f"No AMIs found matching instance-id {source_instance_id}")
            continue

        # Sort and get latest AMI
        latest_ami = sorted(matching_amis, key=lambda x: x['CreationDate'], reverse=True)[0]
        latest_ami_id = latest_ami['ImageId']

        print(f"Latest AMI for instance {source_instance_id}: {latest_ami_id}")

        if current_ami_id == latest_ami_id:
            print(f"Launch template {template_id} already up-to-date with AMI {latest_ami_id}")
            continue

        # Update the launch template
        update_launch_template_with_new_ami(template_id, latest_ami_id)

def update_launch_template_with_new_ami(template_id, latest_ami_id):
    ec2 = boto3.client('ec2')

    # Get the current version of the launch template
    versions = ec2.describe_launch_template_versions(
        LaunchTemplateId=template_id,
        Versions=['$Latest']
    )

    if not versions['LaunchTemplateVersions']:
        print(f"No versions found for launch template {template_id}")
        return

    # Get the data of the latest version
    latest_version_data = versions['LaunchTemplateVersions'][0]['LaunchTemplateData']

    # Update the launch template with the new AMI ID
    new_version_data = latest_version_data.copy()
    new_version_data['ImageId'] = latest_ami_id

    # Create a new launch template version with the updated AMI ID
    response = ec2.create_launch_template_version(
        LaunchTemplateId=template_id,
        VersionDescription='Updated with latest AMI',
        LaunchTemplateData=new_version_data
    )

    if response['LaunchTemplateVersion']:
        print(f"Successfully updated launch template {template_id} with new AMI {latest_ami_id}")
    else:
        print(f"Failed to update launch template {template_id}")

from ..utils.dal import DAL


class ResourcesLogic:
    def __init__(self, region, task_timeout=15):
        self.dal = DAL(region, task_timeout=task_timeout)

    def get_instances(self):
        return [
            {
                'ID': instance['InstanceId'],
                'State': instance['State']['Name'],
                'Type': instance['InstanceType'],
                'Public IP': instance.get('PublicIpAddress', 'N/A'),
            }
            for reservation in self.dal.get_instances()
            for instance in reservation['Instances']
        ]

    def get_vpcs(self):
        return [
            {'VPC ID': vpc['VpcId'], 'CIDR': vpc['CidrBlock']}
            for vpc in self.dal.get_vpcs()
        ]

    def get_load_balancers(self):
        return [
            {'LB Name': lb['LoadBalancerName'], 'DNS Name': lb['DNSName']}
            for lb in self.dal.get_load_balancers()
        ]

    def get_images(self):
        return [
            {'AMI ID': image['ImageId'], 'Name': image.get('Name', 'N/A')}
            for image in self.dal.get_images()
        ]

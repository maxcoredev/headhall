import datetime
import requests
from apps.security.models import BadIp


def update_bad_ips():
    """
    List: https://github.com/stamparm/ipsum
    Requests: https://stackoverflow.com/a/16870677/4117781
    """

    list_of_bad_ips = 'https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt'
    response = requests.get(list_of_bad_ips, stream=True)
    if response.status_code == 200:
        for line in response.iter_lines():
            line = line.decode()

            if not line or line.startswith('#'):
                continue

            ip_address = line.split()[0]
            suspected_count = int(line.split()[1])

            bad_ip, created = BadIp.objects.get_or_create(ip_address=ip_address)
            if not created:
                bad_ip.updated_at = datetime.datetime.utcnow()
                bad_ip.save()

            if bad_ip.suspected_count != suspected_count:
                bad_ip.suspected_count = suspected_count
                bad_ip.save()

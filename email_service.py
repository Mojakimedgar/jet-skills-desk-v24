import os
import urllib.parse
import urllib.request
import json


def _post_form(url, values):
    data = urllib.parse.urlencode(values).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))

def send_enquiry_email(enquiry):
    tenant = os.getenv('MS_TENANT_ID', '').strip()
    client = os.getenv('MS_CLIENT_ID', '').strip()
    secret = os.getenv('MS_CLIENT_SECRET', '').strip()
    sender = os.getenv('MS_MAIL_SENDER', '').strip()
    recipient = os.getenv('JET_CONTACT_EMAIL', 'Mojaki.P@Dhet.gov.za').strip()
    if not all([tenant, client, secret, sender, recipient]):
        return False, 'Email notification is not configured yet.'

    token = _post_form(
        f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        {'client_id': client, 'client_secret': secret, 'scope': 'https://graph.microsoft.com/.default', 'grant_type': 'client_credentials'}
    )['access_token']
    body = {
        'message': {
            'subject': 'JET Skills Desk Website Enquiry',
            'body': {'contentType': 'Text', 'content': (
                f"New JET Skills Desk website enquiry\n\n"
                f"Name: {enquiry['name']}\nEmail: {enquiry['email']}\n"
                f"Organisation: {enquiry.get('organisation','')}\nVisitor contact: {enquiry.get('phone','Not supplied')}\n\n"
                f"Message:\n{enquiry['message']}\n\nReceived: {enquiry['created_at']}"
            )},
            'toRecipients': [{'emailAddress': {'address': recipient}}]
        },
        'saveToSentItems': True
    }
    req = urllib.request.Request(
        f'https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail',
        data=json.dumps(body).encode('utf-8'), method='POST',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.status == 202, f'Graph returned HTTP {response.status}'

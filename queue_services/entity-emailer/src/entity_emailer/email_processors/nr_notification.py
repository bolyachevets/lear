# Copyright © 2021 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Email processing rules and actions for Name Request before expiry, expiry, renewal, upgrade."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from http import HTTPStatus
from pathlib import Path

from entity_queue_common.service_utils import logger
from flask import current_app
from jinja2 import Template
from legal_api.services import NameXService
from legal_api.utils.legislation_datetime import LegislationDatetime

from entity_emailer.email_processors import substitute_template_parts


class Option(Enum):
    """NR notification option."""

    BEFORE_EXPIRY = 'before-expiry'
    EXPIRED = 'expired'
    RENEWAL = 'renewal'
    UPGRADE = 'upgrade'
    REFUND = 'refund'


def get_url(entity_type_cd: str):

    DECIDE_BUSINESS_URL =  current_app.config.get('DECIDE_BUSINESS_URL')
    CORP_FORMS_URL =  current_app.config.get('CORP_FORMS_URL')
    BUSINESS_URL = current_app.config.get('BUSINESS_URL')
    CORP_ONLINE_URL = current_app.config.get('COLIN_URL')
    GENERIC_STEPS = 'Submit appropriate form to BC Registries. Call if assistance required'
    EX_COOP_ASSOC = 'Extraprovincial Cooperative Association'

    url = {
        # BC Types
        'CR':  CORP_ONLINE_URL,
        'UL':  CORP_ONLINE_URL,
        'FR':  DECIDE_BUSINESS_URL,
        'GP':  DECIDE_BUSINESS_URL,
        'DBA': DECIDE_BUSINESS_URL,
        'LP':  CORP_FORMS_URL,
        'LL':  CORP_FORMS_URL,
        'CP':  BUSINESS_URL,
        'BC':  BUSINESS_URL,
        'CC':  CORP_ONLINE_URL,
        'SO': 'BC Social Enterprise',
        'PA': GENERIC_STEPS,
        'FI': GENERIC_STEPS,
        'PAR': GENERIC_STEPS,
        # XPRO and Foreign Types
        'XCR': CORP_ONLINE_URL,
        'XUL': CORP_ONLINE_URL,
        'RLC': CORP_ONLINE_URL,
        'XLP': CORP_FORMS_URL,
        'XLL': CORP_FORMS_URL,
        'XCP': EX_COOP_ASSOC,
        'XSO': EX_COOP_ASSOC,
    }
    return url.get(entity_type_cd, None)


def process(email_info: dict, option) -> dict:  # pylint: disable-msg=too-many-locals
    """
    Build the email for Name Request notification.

    valid values of option: Option
    """
    logger.debug('NR %s notification: %s', option, email_info)
    nr_number = email_info['identifier']
    template = Path(f'{current_app.config.get("TEMPLATE_PATH")}/NR-{option.upper()}.html').read_text()
    filled_template = substitute_template_parts(template)

    nr_response = NameXService.query_nr_number(nr_number)
    if nr_response.status_code != HTTPStatus.OK:
        logger.error('Failed to get nr info for name request: %s', nr_number)
        return {}

    nr_data = nr_response.json()

    expiration_date = ''
    if nr_data['expirationDate']:
        exp_date = datetime.fromisoformat(nr_data['expirationDate'])
        exp_date_tz = LegislationDatetime.as_legislation_timezone(exp_date)
        expiration_date = LegislationDatetime.format_as_report_string(exp_date_tz)

    refund_value = ''
    if option == Option.REFUND.value:
        refund_value = email_info.get('data', {}).get('request', {}).get('refundValue', None)

    legal_name = ''
    for n_item in nr_data['names']:
        if n_item['state'] in ('APPROVED', 'CONDITION'):
            legal_name = n_item['name']
            break

    name_request_url = get_url(nr_data["entity_type_cd"])
    decide_business_url = current_app.config.get('DECIDE_BUSINESS_URL')

    # render template with vars
    mail_template = Template(filled_template, autoescape=True)
    html_out = mail_template.render(
        nr_number=nr_number,
        expiration_date=expiration_date,
        legal_name=legal_name,
        refund_value=refund_value,
        name_request_url=name_request_url,
        decide_business_url=decide_business_url
    )

    # get recipients
    recipients = nr_data['applicants']['emailAddress']
    if not recipients:
        return {}

    subjects = {
        Option.BEFORE_EXPIRY.value: 'Expiring Soon',
        Option.EXPIRED.value: 'Expired',
        Option.RENEWAL.value: 'Confirmation of Renewal',
        Option.UPGRADE.value: 'Confirmation of Upgrade',
        Option.REFUND.value: 'Refund request confirmation'
    }

    return {
        'recipients': recipients,
        'requestBy': 'BCRegistries@gov.bc.ca',
        'content': {
            'subject': f'{nr_number} - {subjects[option]}',
            'body': f'{html_out}',
            'attachments': []
        }
    }

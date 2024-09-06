# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making
蓝鲸流程引擎服务 (BlueKing Flow Engine Service) available.
Copyright (C) 2024 THL A29 Limited,
a Tencent company. All rights reserved.
Licensed under the MIT License (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the
specific language governing permissions and limitations under the License.

We undertake not to change the open source license (MIT license) applicable

to the current version of the project delivered to anyone in the future.
"""
import json
import logging

from apigw_manager.apigw.decorators import apigw_require
from blueapps.account.decorators import login_exempt
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from bkflow.apigw.decorators import check_jwt_and_space, return_json_response
from bkflow.apigw.serializers.space_config import RenewSpaceConfigSerializer
from bkflow.apigw.utils import get_space_config_presentation
from bkflow.space.models import SpaceConfig
from bkflow.utils import err_code

logger = logging.getLogger("root")


@login_exempt
@csrf_exempt
@require_POST
@apigw_require
@check_jwt_and_space
@return_json_response
def renew_space_config(request, space_id):
    data = json.loads(request.body)

    ser = RenewSpaceConfigSerializer(data=data)
    ser.is_valid(raise_exception=True)

    logger.info("[apigw->create_space_config] start renew a space_config, {}".format(ser.data))
    config = ser.validated_data.pop("config", {})

    with transaction.atomic():
        SpaceConfig.objects.batch_update(space_id=space_id, configs=config)

    space_config_presentation = get_space_config_presentation(space_id)
    return {"result": True, "data": space_config_presentation, "code": err_code.SUCCESS.code}

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
import datetime
import logging

from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _

from bkflow.constants import TemplateOperationSource, TemplateOperationType
from bkflow.contrib.operation_record.models import BaseOperateRecord
from bkflow.utils.md5 import compute_pipeline_md5
from bkflow.utils.models import CommonModel, CommonSnapshot

logger = logging.getLogger("root")


class Template(CommonModel):
    """
    字段说明:
    notify_type : 通知类型存储的是一个列表
    notify_receivers : {'receiver_group': ['Maintainers'], 'more_receiver': 'username1,username2'}
    snapshot_id : 因为在新的流程中，一个版本对应一个流程，对应修改都是原地修改
    """

    id = models.BigAutoField(_("模版ID"), primary_key=True)
    space_id = models.IntegerField(_("空间ID"))
    snapshot_id = models.BigIntegerField(_("模板对应的数据ID"))
    name = models.CharField(_("模版名称"), max_length=128)
    desc = models.CharField(_("描述"), max_length=256, null=True, blank=True)
    notify_config = models.JSONField(_("流程事件通知配置"), default=dict)
    scope_type = models.CharField(_("流程范围类型"), max_length=128, null=True, blank=True)
    scope_value = models.CharField(_("流程范围"), max_length=128, null=True, blank=True)
    source = models.CharField(_("来源"), max_length=32, null=True, blank=True, help_text=_("第三方系统对应的资源ID"))
    version = models.CharField(_("版本号"), max_length=32, null=False, blank=False)
    is_enabled = models.BooleanField(_("是否启用"), default=True)
    extra_info = models.JSONField(_("额外的扩展信息"), default=dict)

    class Meta:
        verbose_name = _("流程模板")
        verbose_name_plural = _("流程模板信息表")
        index_together = ["space_id", "scope_type", "scope_value"]

    def to_json(self, with_pipeline_tree=True):
        result = {
            "id": self.id,
            "space_id": self.space_id,
            "name": self.name,
            "desc": self.desc,
            "notify_config": self.notify_config,
            "scope_type": self.scope_type,
            "scope_value": self.scope_value,
            "source": self.source,
            "version": self.version,
            "is_enabled": self.is_enabled,
            "extra_info": self.extra_info,
            "creator": self.creator,
            "create_at": self.create_at,
            "update_at": self.update_at,
            "updated_by": self.updated_by,
        }
        if with_pipeline_tree:
            result["pipeline_tree"] = self.pipeline_tree
        return result

    @classmethod
    def exists(cls, template_id):
        return cls.objects.filter(id=template_id).exists()

    @property
    def snapshot(self):
        return TemplateSnapshot.objects.get(id=self.snapshot_id)

    @property
    def pipeline_tree(self):
        return self.snapshot.data

    def build_callback_data(self, operate_type):
        return {"type": "template", "data": {"id": self.id, "operate_type": operate_type}}

    def update_snapshot(self, pipeline_tree):
        if self.snapshot.has_change(pipeline_tree):
            try:
                TemplateSnapshot.objects.filter(id=self.snapshot_id).update(
                    data=pipeline_tree, md5sum=compute_pipeline_md5(pipeline_tree), create_time=datetime.datetime.now()
                )
            except Exception as e:
                logger.error("[Template->update_snapshot] update snapshot error, error = {}".format(e))

    def create_flow(self, username) -> int:
        """
        根据模板创建flow
        """
        return


class TemplateSnapshot(CommonSnapshot):
    """
    默认模板快照
    """

    template_id = models.BigIntegerField(help_text=_("模板ID"), null=True)

    class Meta:
        verbose_name = _("模板快照")
        verbose_name_plural = _("模板快照表")
        ordering = ["-id"]

    @classmethod
    def create_snapshot(cls, pipeline_tree):
        return cls.objects.create(data=pipeline_tree, md5sum=compute_pipeline_md5(pipeline_tree))


class TemplateOperationRecord(BaseOperateRecord):
    """模版操作记录"""

    operate_type = models.CharField(
        _("操作类型"), choices=[(_type.name, _type.value) for _type in TemplateOperationType], max_length=64
    )
    operate_source = models.CharField(
        _("操作来源"), choices=[(_source.name, _source.value) for _source in TemplateOperationSource], max_length=64
    )

    class Meta:
        verbose_name = _("模版操作记录")
        verbose_name_plural = _("模版操作记录")
        indexes = [models.Index(fields=["instance_id"])]
        ordering = ["-id"]


class TemplateMockDataManager(models.Manager):
    def batch_create(self, operator: str, space_id: int, template_id: int, mock_data: dict, *args, **kwargs):
        objs = [
            TemplateMockData(
                space_id=space_id,
                template_id=template_id,
                node_id=node_id,
                data=data["data"],
                is_default=data["is_default"],
                operator=operator,
                name=data["name"],
            )
            for node_id, mock_data_list in mock_data.items()
            for data in mock_data_list
        ]
        self.bulk_create(objs)
        return self.filter(space_id=space_id, template_id=template_id)

    def batch_update(self, operator: str, space_id: int, template_id: int, mock_data: dict, *args, **kwargs):
        existing_ones = self.filter(space_id=space_id, template_id=template_id)
        mock_data_mappings = {data.id: data for data in existing_ones}

        flatten_mock_data = (
            (node_id, data) for node_id, mock_data_list in mock_data.items() for data in mock_data_list
        )

        # 根据是否有 id 来判断是新增数据还是更新数据
        update_ones = []
        update_ids = []
        new_ones = []

        for node_id, data in flatten_mock_data:
            if "id" in data:
                data_id = data.pop("id")
                update_ids.append(data_id)
                mock_data_obj = mock_data_mappings[data_id]
                mock_data_obj.name = data["name"]
                mock_data_obj.data = data["data"]
                mock_data_obj.is_default = data["is_default"]
                mock_data_obj.operator = operator
                mock_data_obj.node_id = node_id
                update_ones.append(mock_data_obj)
            else:
                new_ones.append(
                    TemplateMockData(
                        space_id=space_id,
                        template_id=template_id,
                        node_id=node_id,
                        data=data["data"],
                        is_default=data["is_default"],
                        operator=operator,
                        name=data["name"],
                    )
                )

        remove_ids = set(mock_data_mappings.keys()) - set(update_ids)
        try:
            with transaction.atomic():
                self.bulk_update(update_ones, ["name", "data", "is_default", "operator", "update_at", "node_id"])
                self.bulk_create(new_ones)
                self.filter(id__in=remove_ids).delete()
        except Exception as e:
            logger.exception(f"[TemplateMockDataManager] mock data batch update failed: {e}")
            raise e
        return self.filter(space_id=space_id, template_id=template_id)


class TemplateMockData(models.Model):
    name = models.CharField("Mock Data Name", max_length=128)
    space_id = models.IntegerField("Space ID")
    template_id = models.BigIntegerField("Template ID")
    node_id = models.CharField("Node ID", max_length=33)
    data = models.JSONField("Mock Data")
    is_default = models.BooleanField("Is Default", default=False)
    extra_info = models.JSONField("Extra Info", null=True, blank=True)
    operator = models.CharField("operator", max_length=32, null=True, blank=True)
    create_at = models.DateTimeField(_("创建时间"), auto_now_add=True, db_index=True)
    update_at = models.DateTimeField(_("更新时间"), auto_now=True)

    objects = TemplateMockDataManager()

    class Meta:
        verbose_name = "Template Mock Data"
        verbose_name_plural = "Template Mock Data"
        ordering = ["-id"]
        index_together = ["space_id", "template_id", "node_id"]


class TemplateMockScheme(models.Model):
    space_id = models.IntegerField("Space ID")
    template_id = models.BigIntegerField("Template ID")
    data = models.JSONField("Mock Scheme Data")
    operator = models.CharField("operator", max_length=32, null=True, blank=True)
    create_at = models.DateTimeField(_("创建时间"), auto_now_add=True, db_index=True)
    update_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        verbose_name = "Template Mock Scheme"
        verbose_name_plural = "Template Mock Scheme"
        ordering = ["-id"]
        index_together = ["space_id", "template_id"]

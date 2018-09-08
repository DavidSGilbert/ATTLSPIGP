#!/usr/local/bin/python3
import logging
import socket
from itertools import chain
# from typing import List

from nfdk.model_v2.simple_model_pojo_pool import SimpleModelPojoPool
from nfdk.plugin.output_formaters import textual_output, tabular_output
from nfdk.plugin.plugin_base import PluginBase, PluginType
from nfdk.pojos.model import RouterInventoryItem
from nfdk.pojos.model_enums import LinkLayerEnum, InventoryItemTypeEnum
from nfdk.utils.brain_rest_connector import BrainRestConnector

DELIMITER = ','


class LspIgpPath(PluginBase):
    """
    Present detailed information of a specific router
    """
    GUID = "LspIgpPath"
    NAME = "LSP IGP Paths"
    VERSION = "1.00"
    PLUGIN_TYPE = PluginType.REPORT
    DESCRIPTION = "Present the IGP path of an LSP"
    PARAMS_SCHEMA = {
        'type': 'object',
        'properties': {
            'router_id': {
                'description': "System name or management IP",
                'title': "Router Name or IP",
                'type': 'string',
            },
            'lsp_name': {
                'description': "LSP Name",
                'title': "LSP name",
                'type': 'string'
            }
        },
        'required': ['router_id', 'lsp_name'],
    }

    def __init__(self, brain_opts, params):
        self._logger = logging.getLogger(self.GUID)
        self._model = SimpleModelPojoPool.create_with_rest_connector_from_config_opts(brain_opts,
                                                                                      fail_on_missing_pojo=False)
        self.brain_rest_connector = BrainRestConnector.create_from_config_opts(brain_opts)
        self._router_id = params.get("router_id").strip()
        self._lsp_name = params.get("lsp_name").strip()
        self._encapsulate_output = params.get("formatOutput", True)

    async def run(self, loop):
        if not self._router_id:
            return textual_output("Must specify a name or IP for the desired network element")
        if not self._lsp_name:
            return textual_output("Must specify a name for the desired LSP")
        await self._model.connector.fetch_inventory(itype=InventoryItemTypeEnum.ROUTER)
        await self._model.connector.fetch_sites()
        await self._model.connector.fetch_paths()
        self._model.resolve_refs()

        matched_routers = [r for r in self._model.all_inventory_items_of_type(InventoryItemTypeEnum.ROUTER)
                           if LspIgpPath.match_router_name_or_ip(r, self._router_id)]
        num_matched_routers = len(matched_routers)
        if num_matched_routers == 0:
            return textual_output("Router not found. Identifier: {}".format(self._router_id))
        router = matched_routers[0]

        link_lists = [await self.brain_rest_connector.get_links(LinkLayerEnum.LSP, root=router.guid)]
        router_lsps = [link for link in chain(*link_lists)]
        matched_lsp = [x for x in router_lsps if self._lsp_name.lower() in x.guid.lower()]
        num_matched_lsps = len(matched_lsp)
        if num_matched_lsps == 0:
            return textual_output("LSP not found. Identifier: {}".format(self._lsp_name))
        lsp = matched_lsp[0]

        rows = []
        if lsp.paths:
            lsp_path_guid = [x.guid for x in lsp.paths]
            lsp_path = self._model.get_by_guid(lsp_path_guid[0])
            row = []
            for path_hop in lsp_path.hops:
                temp = path_hop.link_non_throwing.guid.split('/')
                if path_hop.direction.name == "B_TO_A":
                    row.append([temp[4], temp[5]])
                    row.append([temp[2], temp[3]])
                if path_hop.direction.name == "A_TO_B":
                    row.append([temp[2], temp[3]])
                    row.append([temp[4], temp[5]])
            for line in row:
                igp_router = self._model.get_by_guid(f'IN/{line[0]}')
                site = igp_router.site_non_throwing
                rows.append([site.name, igp_router.name, line[0], line[1]])

        rows.append([''])
        rows.append([f'Router {router.name} ({router.guid}) sees {len(router_lsps)} LSPs'])
        rows.append([f'LSP {lsp.name} ({lsp.guid})'])
        rows.append([f'LSP Status is {lsp.oper_status.name}'])
        return self.format_output_data(['Site Name', 'Router Name', 'Router Mgt. IP', 'IGP IP'], rows)

    def format_output_data(self, headers, rows):
        if self._encapsulate_output:
            result = tabular_output(headers=headers, data=rows)
        else:
            result = DELIMITER.join(headers)
            for row in rows:
                result += '\n' + DELIMITER.join(row)
        return result

    async def cleanup(self):
        await self._model.connector.close()
        await self.brain_rest_connector.close_connection()

    @staticmethod
    def match_router_name_or_ip(router: RouterInventoryItem, search_str):
        try:
            # legal
            socket.inet_aton(search_str)
            is_ip_v4 = True
        except socket.error:
            # Not legal
            is_ip_v4 = False
        return is_ip_v4 and router.management_ip == search_str or router.name == search_str


if __name__ == '__main__':
    LspIgpPath.cli()

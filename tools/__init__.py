# -*- coding: utf-8 -*-
"""Реестр всех инструментов Claude."""

from tools.stock import STOCK_TOOLS, STOCK_TOOL_MAP
from tools.sales import SALES_TOOLS, SALES_TOOL_MAP
from tools.orders import ORDERS_TOOLS, ORDERS_TOOL_MAP
from tools.finance import FINANCE_TOOLS, FINANCE_TOOL_MAP
from tools.production import PRODUCTION_TOOLS, PRODUCTION_TOOL_MAP
from tools.counterparty import COUNTERPARTY_TOOLS, COUNTERPARTY_TOOL_MAP
from tools.warehouse import WAREHOUSE_TOOLS, WAREHOUSE_TOOL_MAP
from tools.digest import DIGEST_TOOLS, DIGEST_TOOL_MAP
from tools.audit import AUDIT_TOOLS, AUDIT_TOOL_MAP
from tools.planning import PLANNING_TOOLS, PLANNING_TOOL_MAP
from tools.universal import UNIVERSAL_TOOLS, UNIVERSAL_TOOL_MAP

TOOLS = (
    STOCK_TOOLS
    + SALES_TOOLS
    + ORDERS_TOOLS
    + FINANCE_TOOLS
    + PRODUCTION_TOOLS
    + COUNTERPARTY_TOOLS
    + WAREHOUSE_TOOLS
    + DIGEST_TOOLS
    + AUDIT_TOOLS
    + PLANNING_TOOLS
    + UNIVERSAL_TOOLS
)

TOOL_MAP = {
    **STOCK_TOOL_MAP,
    **SALES_TOOL_MAP,
    **ORDERS_TOOL_MAP,
    **FINANCE_TOOL_MAP,
    **PRODUCTION_TOOL_MAP,
    **COUNTERPARTY_TOOL_MAP,
    **WAREHOUSE_TOOL_MAP,
    **DIGEST_TOOL_MAP,
    **AUDIT_TOOL_MAP,
    **PLANNING_TOOL_MAP,
    **UNIVERSAL_TOOL_MAP,
}

from agent_runtime.common import *
from agent_runtime.common import TOOLS as BASE_TOOLS
from product_core.paths import ASSETS,within_state
TOOLS=(*BASE_TOOLS,'search_knowledge','assign_segments','query_association_rules')
within_run=within_state
def accepted_segmentation():
    from product_core.release import asset_trust
    return ASSETS/'segmentation',asset_trust('segmentation')

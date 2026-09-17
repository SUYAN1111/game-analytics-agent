from product_core.release import asset_trust,verify_anchor
from product_core.paths import ASSETS
def host_asset_trust(home,mode):
    trust=asset_trust('association');verify_anchor(home,trust,'association');return trust

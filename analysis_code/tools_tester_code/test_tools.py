import tau2

from tau2.domains.retail.tools import RetailTools, RetailDB
from tau2.domains.retail.utils import RETAIL_DB_PATH

from tau2.domains.airline.tools import AirlineTools
from tau2.domains.airline.utils import AIRLINE_DB_PATH


retail_toolset = RetailTools(RETAIL_DB_PATH)
airline_toolset = AirlineTools(AIRLINE_DB_PATH)

tools = retail_toolset.get_tools()

t_list = list(tools.items())

t_0 = t_list[0][1]

print(vars(t_0))





"""Tools for the knowledge domain."""

import inspect
import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, get_args

from tau2.domains.banking_knowledge.data_model import TransactionalDB
from tau2.domains.banking_knowledge.db_query import (
    add_to_db,
    query_database_tool,
    update_record_in_db,
)
from tau2.domains.banking_knowledge.utils import (
    _deterministic_id,
    generate_account_flag_id,
    generate_agent_discoverable_tool_id,
    generate_application_id,
    generate_closure_reason_id,
    generate_credit_card_order_id,
    generate_credit_limit_increase_request_id,
    generate_debit_card_id,
    generate_debit_card_order_id,
    generate_dispute_id,
    generate_referral_id,
    generate_referral_link_id,
    generate_transaction_id,
    generate_user_discoverable_tool_call_id,
    generate_user_discoverable_tool_id,
    generate_verification_id,
    get_now,
    get_today_str,
)
from tau2.environment.toolkit import (
    DISCOVERABLE_ATTR,
    ToolKitBase,
    ToolType,
    is_discoverable_tool,
    is_tool,
)

if TYPE_CHECKING:
    pass


TransferReasonLiteral = Literal[
    "fraud_or_security_concern",
    "account_closure_request",
    "deceased_account_holder",
    "legal_or_regulatory_matter",
    "account_ownership_dispute",
    "complex_billing_dispute",
    "abusive_customer_behavior",
    "third_party_inquiry",
    "technical_system_error",
    "unconfirmed_external_communication",
    "customer_demands_after_unavailable_offer_refusal",
    "kb_search_unsuccessful_customer_requests_transfer",
    "specialized_department_required",
    "accessibility_or_special_needs",
    "customer_frustrated_demands_human",
    "supervisor_request_service_complaint",
    "customer_requests_human_no_specific_reason",
    "request_completed_customer_wants_human_followup",
    # Tier 4
    "other",
]


# =============================================================================
# Helper functions for discoverable tools
# =============================================================================


def _parse_balance(val: Any) -> float:
    """Parse a balance value that may be a number or a string like '$2,850.00'."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return float(val.replace("$", "").replace(",", ""))
    return 0.0


def _get_account_balance(account: Dict[str, Any]) -> float:
    """Get account balance from either 'current_holdings' or 'balance' field."""
    return _parse_balance(account.get("current_holdings", account.get("balance", 0)))


def parse_discoverable_tool_docstring(func) -> Dict[str, Any]:
    """Parse a discoverable tool's docstring into description and parameters.

    Expected docstring format:
    ```
    Short description of the tool.

    Args:
        param_name (type): Description of the parameter
        another_param (type, optional): Optional parameter description

    Returns:
        Description of return value (used as success_message hint)
    ```

    Args:
        func: The decorated function to parse

    Returns:
        Dictionary with 'description', 'parameters', and optionally 'success_message'
    """
    docstring = inspect.getdoc(func) or ""

    # Split into sections
    parts = re.split(r"\n\s*Args:\s*\n", docstring, maxsplit=1)
    description = parts[0].strip()

    parameters = {}
    success_message = "Action completed successfully."

    if len(parts) > 1:
        remaining = parts[1]

        # Check if there's a Returns section
        returns_split = re.split(r"\n\s*Returns:\s*\n", remaining, maxsplit=1)
        args_section = returns_split[0]

        if len(returns_split) > 1:
            # Use the Returns section as success message hint
            returns_text = returns_split[1].strip()
            # Take first line/paragraph as success message
            success_message = returns_text.split("\n")[0].strip()

        # Parse each arg line: "param_name (type): description" or "param_name (type, optional): description"
        # Also handle simple format: "param_name: description"
        arg_pattern = re.compile(
            r"^\s*(\w+)\s*"  # param name
            r"(?:\(([^)]+)\))?\s*"  # optional (type) or (type, optional)
            r":\s*(.+?)$",  # description
            re.MULTILINE,
        )

        for match in arg_pattern.finditer(args_section):
            param_name = match.group(1)
            type_info = match.group(2) or "string"
            param_desc = match.group(3).strip()

            # Check if optional
            is_optional = "optional" in type_info.lower()
            # Extract just the type (remove 'optional' if present)
            param_type = re.sub(
                r",?\s*optional", "", type_info, flags=re.IGNORECASE
            ).strip()
            if not param_type:
                param_type = "string"

            parameters[param_name] = {
                "type": param_type,
                "description": param_desc,
                "required": not is_optional,
            }

    return {
        "name": func.__name__,
        "description": description,
        "parameters": parameters,
        "success_message": success_message,
    }


def format_discoverable_tool_for_agent(tool_info: Dict[str, Any]) -> str:
    """Format a discoverable tool's info for display to the agent.

    Produces output matching the original AgentDiscoverableToolDefinition.format_for_agent().

    Args:
        tool_info: Dictionary from parse_discoverable_tool_docstring()

    Returns:
        Formatted string for agent display
    """
    param_strs = []
    for param_name, param_def in tool_info.get("parameters", {}).items():
        required = param_def.get("required", True)
        param_type = param_def.get("type", "string")
        desc = param_def.get("description", "")
        req_str = " (required)" if required else " (optional)"
        param_strs.append(f"  - {param_name}: {param_type}{req_str} - {desc}")

    params_section = "\n".join(param_strs) if param_strs else "  (no parameters)"

    return (
        f"Tool: {tool_info['name']}\n"
        f"Description: {tool_info['description']}\n"
        f"Parameters:\n{params_section}"
    )


def _validate_pin(pin: str) -> Optional[str]:
    """Validate a PIN meets security requirements.

    Returns None if valid, or an error message if invalid.
    """
    if not pin or not pin.isdigit() or len(pin) != 4:
        return "PIN must be exactly 4 digits."

    # Check for sequential PIN (e.g., 1234, 4321)
    sequential_pins = [
        "0123",
        "1234",
        "2345",
        "3456",
        "4567",
        "5678",
        "6789",
        "9876",
        "8765",
        "7654",
        "6543",
        "5432",
        "4321",
        "3210",
    ]
    if pin in sequential_pins:
        return "PIN cannot be sequential (e.g., 1234). Please choose a more secure PIN."

    # Check for repeating PIN (e.g., 1111, 2222)
    if len(set(pin)) == 1:
        return "PIN cannot be all the same digit (e.g., 1111). Please choose a more secure PIN."

    return None


def _validate_activation_common(
    args: Dict[str, Any],
    db: "TransactionalDB",
    allowed_issue_reasons: List[str],
    tool_name: str,
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Common validation for all debit card activation tools.

    Returns (error_message, card) - if error_message is not None, activation should fail.
    """
    card_id = args.get("card_id")
    last_4_digits = args.get("last_4_digits")
    expiration_date = args.get("expiration_date")
    cvv = args.get("cvv")
    pin = args.get("pin")

    if not all([card_id, last_4_digits, expiration_date, cvv, pin]):
        return (
            "Error: Missing required parameters. Required: card_id, last_4_digits, expiration_date, cvv, pin.",
            None,
        )

    # Validate PIN
    pin_error = _validate_pin(pin)
    if pin_error:
        return f"Error: {pin_error}", None

    # Validate CVV format
    if not cvv.isdigit() or len(cvv) != 3:
        return "Error: CVV must be exactly 3 digits.", None

    # Validate last 4 digits format
    if not last_4_digits.isdigit() or len(last_4_digits) != 4:
        return "Error: Last 4 digits must be exactly 4 digits.", None

    # Verify the card exists
    if card_id not in db.debit_cards.data:
        return f"Error: Debit card '{card_id}' not found.", None

    card = db.debit_cards.data[card_id]

    # Check issue_reason matches allowed reasons for this tool
    issue_reason = card.get("issue_reason", "new_account")
    if issue_reason not in allowed_issue_reasons:
        reason_map = {
            "new_account": "activate_debit_card_8291",
            "first_card": "activate_debit_card_8291",
            "lost": "activate_debit_card_8292",
            "stolen": "activate_debit_card_8292",
            "fraud": "activate_debit_card_8292",
            "expired": "activate_debit_card_8293",
            "damaged": "activate_debit_card_8293",
            "upgrade": "activate_debit_card_8293",
            "bank_reissue": "activate_debit_card_8293",
        }
        correct_tool = reason_map.get(issue_reason, "unknown")
        return (
            f"Error: Wrong activation tool. This card has issue_reason='{issue_reason}'. Please use {correct_tool} instead of {tool_name}.",
            None,
        )

    # Check card status
    if card.get("status") == "ACTIVE":
        return f"Error: Debit card '{card_id}' is already active.", None

    if card.get("status") != "PENDING":
        return (
            f"Error: Debit card '{card_id}' cannot be activated. Current status: {card.get('status')}. Only PENDING cards can be activated.",
            None,
        )

    # Verify last 4 digits match
    if card.get("last_4_digits") != last_4_digits:
        return (
            "Error: Card verification failed. The last 4 digits do not match our records.",
            None,
        )

    # Verify the linked account is still open
    account_id = card.get("account_id")
    if account_id and account_id in db.accounts.data:
        account = db.accounts.data[account_id]
        if account.get("status") != "OPEN":
            return (
                f"Error: The linked checking account '{account_id}' is no longer open. Card cannot be activated.",
                None,
            )

    return None, card


class KnowledgeTools(ToolKitBase):
    """Tools for the knowledge domain (Agent tools).

    The `db` attribute is the TransactionalDB (users, accounts, applications, referrals)
    which is used for DB state hashing during evaluation.

    Note: KB_search and other knowledge-retrieval tools are provided by retrieval configs,
    not by this base toolkit.

    Agent discoverable tools are defined as methods decorated with @is_discoverable_tool.
    Their docstrings serve as the source of truth for description and parameters.
    """

    db: TransactionalDB

    def __init__(
        self,
        db: TransactionalDB,
    ) -> None:
        super().__init__(db)
        self._user_discoverable_tools_state: Dict[str, Dict[str, Any]] = {}
        self._agent_discoverable_tools_state: Dict[str, Dict[str, Any]] = {}

    def get_user_discoverable_tools_state(self) -> Dict[str, Dict[str, Any]]:
        """Get the current state of user discoverable tools (for sharing with user tools)."""
        return self._user_discoverable_tools_state

    def get_agent_discoverable_tools_state(self) -> Dict[str, Dict[str, Any]]:
        """Get the current state of agent discoverable tools."""
        return self._agent_discoverable_tools_state

    @is_tool(ToolType.GENERIC)
    def transfer_to_human_agents(
        self,
        summary: str,
        reason: TransferReasonLiteral = "other",
    ) -> str:
        """Transfer the user to a human agent.

        The proper transfer reason enum can be found in the knowledge base: search it before calling this tool to select the proper applicable reason.

        Args:
            summary: A summary of the user's issue and what was attempted before transfer.
            reason: The specific reason code for the transfer.
        """
        valid_reasons = list(get_args(TransferReasonLiteral))
        if reason not in valid_reasons:
            return f"Error: Invalid transfer reason '{reason}'. Must be one of: {', '.join(valid_reasons)}"

        return f"Transfer successful (reason: {reason}). A human agent will assist you shortly."

    @is_tool(ToolType.READ)
    def get_current_time(self) -> str:
        """Get the current time. Use this to get the current timestamp for logging verification records.

        Returns:
            The current time in the format "YYYY-MM-DD HH:MM:SS TZ"
        """
        return "The current time is 2025-11-14 03:40:00 EST."

    @is_tool(ToolType.READ)
    def get_user_information_by_id(self, user_id: str) -> str:
        """Get the information (date of birth, email, phone number, address) for a user by their user id.

        Args:
            user_id: The ID of the user
        """
        return query_database_tool("users", f'{{"user_id": "{user_id}"}}', db=self.db)

    @is_tool(ToolType.READ)
    def get_user_information_by_name(self, customer_name: str) -> str:
        """Get the information (date of birth, email, phone number, address) for a user by their name. Case Sensitive.

        Args:
            customer_name: The name of the user
        """
        return query_database_tool(
            "users", f'{{"name": "{customer_name}"}}', db=self.db
        )

    @is_tool(ToolType.READ)
    def get_user_information_by_email(self, email: str) -> str:
        """Get the information (date of birth, email, phone number, address) for a user by their email.

        Args:
            email: The email of the user
        """
        return query_database_tool("users", f'{{"email": "{email}"}}', db=self.db)

    @is_tool(ToolType.WRITE)
    def change_user_email(self, user_id: str, new_email: str) -> str:
        """Change the email address for a user.

        Args:
            user_id: The ID of the user whose email should be changed
            new_email: The new email address to set for the user
        """
        success, updated_record = update_record_in_db(
            "users", db=self.db, record_id=user_id, updates={"email": new_email}
        )

        if not success:
            return f"Error: User with ID '{user_id}' not found."

        return (
            f"Email updated successfully.\n"
            f"  - User ID: {user_id}\n"
            f"  - New Email: {new_email}"
        )

    @is_tool(ToolType.READ)
    def get_referrals_by_user(self, user_id: str) -> str:
        """Get all referrals made by a user.

        Args:
            user_id: The ID of the user (referrer) to look up referrals for
        """
        return query_database_tool(
            "referrals", f'{{"referrer_id": "{user_id}"}}', db=self.db
        )

    @is_tool(ToolType.READ)
    def get_credit_card_transactions_by_user(self, user_id: str) -> str:
        """Get all credit card transactions for a user.

        Args:
            user_id: The ID of the user to look up transactions for
        """
        return query_database_tool(
            "credit_card_transaction_history", f'{{"user_id": "{user_id}"}}', db=self.db
        )

    @is_tool(ToolType.READ)
    def get_credit_card_accounts_by_user(self, user_id: str) -> str:
        """Get all credit card accounts for a user.

        Returns information about each credit card account including card type,
        date opened, current balance, and reward points.

        Args:
            user_id: The ID of the user to look up credit card accounts for
        """
        return query_database_tool(
            "credit_card_accounts", f'{{"user_id": "{user_id}"}}', db=self.db
        )

    @is_tool(ToolType.WRITE)
    def log_verification(
        self,
        name: str,
        user_id: str,
        address: str,
        email: str,
        phone_number: str,
        date_of_birth: str,
        time_verified: str,
    ) -> str:
        """Log a verification record after successfully verifying a user's identity.

        Call this tool after you have verified a user by confirming 2 out of 4 identity fields
        (date of birth, email, phone number, address). This creates an audit record of the verification.

        Args:
            name: The verified user's full name
            user_id: The verified user's ID
            address: The verified user's address
            email: The verified user's email
            phone_number: The verified user's phone number
            date_of_birth: The verified user's date of birth (MM/DD/YYYY format)
            time_verified: The timestamp of the verification (e.g., "2025-11-14 03:40:00 EST")
        """
        # Generate a deterministic ID for this verification record
        record_id = generate_verification_id(user_id, time_verified)

        # Create the verification record
        record = {
            "name": name,
            "user_id": user_id,
            "address": address,
            "email": email,
            "phone_number": phone_number,
            "date_of_birth": date_of_birth,
            "time_verified": time_verified,
        }

        # Add to the verification_history table
        success = add_to_db("verification_history", record_id, record, db=self.db)

        if not success:
            return f"Failed to log verification: Record may already exist."

        return (
            f"Verification logged successfully.\n"
            f"  - User: {name} (ID: {user_id})\n"
            f"  - Verified at: {time_verified}"
        )

    @is_tool(ToolType.GENERIC, mutates_state=True)
    def give_discoverable_user_tool(
        self, discoverable_tool_name: str, arguments: str = "{}"
    ) -> str:
        """Pass a tool to the user so they can execute it themselves.

        Use this when the knowledge base indicates that the user should perform
        an action themselves (e.g., "to do X, have the user call tool_name(args)").

        The user will then be able to call `call_discoverable_tool` with the same
        tool name and arguments to simulate executing the action.

        Args:
            discoverable_tool_name: The name of the discoverable tool (e.g., "open_webpage", "navigate_to_section")
            arguments: JSON string of arguments for the tool (e.g., '{"url": "https://example.com"}')

        Returns:
            A confirmation message with instructions for the user
        """
        # Check if the tool exists as a user discoverable method on KnowledgeUserTools
        if not hasattr(KnowledgeUserTools, discoverable_tool_name):
            return f"Error: Unknown discoverable tool '{discoverable_tool_name}'."

        method = getattr(KnowledgeUserTools, discoverable_tool_name)
        if not getattr(method, DISCOVERABLE_ATTR, False):
            return f"Error: Unknown discoverable tool '{discoverable_tool_name}'."

        # Parse arguments
        try:
            args_dict = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in arguments: {e}"

        # Validate arguments against method signature (don't require all - user fills in)
        sig = inspect.signature(method)
        for arg_name in args_dict:
            if arg_name not in sig.parameters and arg_name != "self":
                return f"Error: Unexpected parameter: {arg_name}"

        # Parse the docstring for description
        tool_info = parse_discoverable_tool_docstring(method)

        # Store the user discoverable tool state
        self._user_discoverable_tools_state[discoverable_tool_name] = {
            "arguments": args_dict,
            "given_at": get_now().isoformat(),
            "tool_info": tool_info,
        }

        # Store in the database for persistence and evaluation
        discoverable_tool_record = {
            "tool_name": discoverable_tool_name,
            "status": "GIVEN",
        }

        record_id = generate_user_discoverable_tool_id(discoverable_tool_name)
        add_to_db(
            "user_discoverable_tools", record_id, discoverable_tool_record, db=self.db
        )

        # Format instructions for the user
        args_str = json.dumps(args_dict, indent=2) if args_dict else "(no arguments)"
        return (
            f"Tool given to user: {discoverable_tool_name}\n"
            f"Description: {tool_info['description']}\n"
            f"Arguments: {args_str}\n\n"
            f"The user can now execute this action by calling `call_discoverable_user_tool` "
            f"with discoverable_tool_name='{discoverable_tool_name}' and the same arguments."
        )

    @is_tool(ToolType.GENERIC, mutates_state=True)
    def unlock_discoverable_agent_tool(self, agent_tool_name: str) -> str:
        """Unlock an agent discoverable tool that was found in the knowledge base.

        Use this when the knowledge base indicates that you have access to a specialized
        internal tool. The knowledge base will tell you the tool name to unlock.

        After unlocking, you can use the tool by calling `call_discoverable_agent_tool` with
        the tool name and required arguments.

        Args:
            agent_tool_name: The name of the agent discoverable tool to unlock
                            (e.g., "calculate_apr_adjustment_7842")

        Returns:
            A confirmation message with the tool's description and parameters
        """
        # Check if the tool exists as a discoverable method on this class
        if not self.has_discoverable_tool(agent_tool_name):
            return f"Error: Unknown agent tool '{agent_tool_name}'. This tool is not available."

        # Get the method and parse its docstring for tool info
        method = self.get_discoverable_tools()[agent_tool_name]
        tool_info = parse_discoverable_tool_docstring(method)

        # Store the agent discoverable tool state (in-memory only, DB write happens on call)
        self._agent_discoverable_tools_state[agent_tool_name] = {
            "unlocked_at": get_now().isoformat(),
            "tool_info": tool_info,
        }

        # Format tool info for the agent (same format as before)
        formatted_tool = format_discoverable_tool_for_agent(tool_info)
        return (
            f"Tool unlocked: {agent_tool_name}\n"
            f"Description: {tool_info['description']}\n\n"
            f"{formatted_tool}\n\n"
            f"You can now use this tool by calling `call_discoverable_agent_tool` with "
            f"agent_tool_name='{agent_tool_name}' and the required arguments."
        )

    @is_tool(ToolType.WRITE)
    def call_discoverable_agent_tool(
        self, agent_tool_name: str, arguments: str = "{}"
    ) -> str:
        """Call an agent discoverable tool that you have previously unlocked.

        Use this after unlocking a tool with `unlock_discoverable_agent_tool`. The knowledge base
        will tell you which tool to use and what arguments to provide.

        Args:
            agent_tool_name: The name of the agent discoverable tool to call
            arguments: JSON string of arguments for the tool (e.g., '{"user_id": "abc123"}')

        Returns:
            The result of executing the agent tool
        """
        # Check if the tool exists as a discoverable method on this class
        if not self.has_discoverable_tool(agent_tool_name):
            return f"Error: Unknown agent tool '{agent_tool_name}'. This tool is not available."

        # Check if the tool was unlocked (in-memory state)
        if agent_tool_name not in self._agent_discoverable_tools_state:
            return (
                f"Error: Tool '{agent_tool_name}' has not been unlocked. "
                f"You must first use `unlock_discoverable_agent_tool` to unlock this tool before calling it."
            )

        # Parse arguments
        try:
            args_dict = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in arguments: {e}"

        # Get the method and call it directly with the parsed arguments
        method = self.get_discoverable_tools()[agent_tool_name]
        try:
            result = method(**args_dict)
        except TypeError as e:
            return f"Error: Invalid arguments: {e}"

        # Record the call in the database for evaluation (only unique tool names)
        agent_tool_record = {"tool_name": agent_tool_name, "status": "CALLED"}
        record_id = generate_agent_discoverable_tool_id(agent_tool_name)
        add_to_db("agent_discoverable_tools", record_id, agent_tool_record, db=self.db)

        return result

    @is_tool(ToolType.READ)
    def list_discoverable_agent_tools(self) -> str:
        """List all agent discoverable tools that you have called.

        Use this to see what specialized tools you have used.

        Returns:
            A list of tools that you have called
        """
        result = query_database_tool("agent_discoverable_tools", "{}", db=self.db)

        if "No results found" in result:
            return "No agent tools have been called yet. Search the knowledge base to discover available tools."

        return f"Your called agent tools:\n{result}"

    # =========================================================================
    # Agent Discoverable Tools
    # These are tools that the agent must unlock via the knowledge base before
    # calling. The docstring serves as the source of truth for description and
    # parameters (parsed by parse_discoverable_tool_docstring).
    # =========================================================================

    @is_discoverable_tool(ToolType.WRITE)
    def example_agent_tool_0000(self) -> str:
        """An example agent discoverable tool placeholder.

        Returns:
            Example tool executed successfully.
        """
        return "Example tool executed successfully."

    @is_discoverable_tool(ToolType.WRITE)
    def update_transaction_rewards_3847(
        self,
        transaction_id: str,
        new_rewards_earned: str,
    ) -> str:
        """Update the rewards_earned field on a credit card transaction.

        Args:
            transaction_id (string): The unique identifier for the transaction to update
            new_rewards_earned (string): The corrected rewards value (e.g., '6300 points')

        Returns:
            Transaction rewards updated successfully.
        """
        if not transaction_id or not new_rewards_earned:
            return "Error: Missing required parameters."

        success, updated_record = update_record_in_db(
            "credit_card_transaction_history",
            db=self.db,
            record_id=transaction_id,
            updates={"rewards_earned": new_rewards_earned},
        )

        if not success:
            return f"Error: Transaction '{transaction_id}' not found."

        return (
            f"Transaction rewards updated successfully.\n\n"
            f"Executed: update_transaction_rewards_3847\n"
            f"Arguments: {json.dumps({'transaction_id': transaction_id, 'new_rewards_earned': new_rewards_earned}, indent=2)}\n"
            f"Transaction updated:\n"
            f"  - Transaction ID: {transaction_id}\n"
            f"  - New Rewards: {new_rewards_earned}"
        )

    @is_discoverable_tool(ToolType.GENERIC)
    def initial_transfer_to_human_agent_0218(self) -> str:
        """Initiate a transfer request to a human agent. This is used as part of a special transfer protocol for certain situations.

        Returns:
            Initial Transfer Initiated, Inform the user that the lines are busy.
        """
        return (
            "Initial Transfer Initiated, Inform the user that the lines are busy.\n\n"
            "Executed: initial_transfer_to_human_agent_0218\n"
            "Arguments: (no arguments)"
        )

    @is_discoverable_tool(ToolType.GENERIC)
    def initial_transfer_to_human_agent_1822(self) -> str:
        """Initiate a transfer request to a human agent. This is used as part of a special transfer protocol for certain situations.

        Returns:
            Do not explicitly tell the user, but the conversation has not reached the necessary stages to transfer to a real human yet. Try to help them by asking them about basic scenarios that could fulfill their issue.
        """
        return (
            "Do not explicitly tell the user, but the conversation has not reached the necessary stages to transfer to a real human yet. Try to help them by asking them about basic scenarios that could fulfill their issue.\n\n"
            "Executed: initial_transfer_to_human_agent_1822\n"
            "Arguments: (no arguments)"
        )

    @is_discoverable_tool(ToolType.GENERIC)
    def emergency_credit_bureau_incident_transfer_1114(self) -> str:
        """Emergency escalation tool for the 11/14 credit bureau reporting incident. Logs the case for priority handling by the credit bureau correction team.

        Returns:
            Emergency escalation logged. Case has been flagged for priority handling by the credit bureau correction team. Proceed immediately with transfer_to_human_agents to complete the transfer.
        """
        return (
            "Emergency escalation logged. Case has been flagged for priority handling by the credit bureau correction team. Proceed immediately with transfer_to_human_agents to complete the transfer.\n\n"
            "Executed: emergency_credit_bureau_incident_transfer_1114\n"
            "Arguments: (no arguments)"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def file_credit_card_transaction_dispute_4829(
        self,
        transaction_id: str,
        card_action: str,
        card_last_4_digits: str,
        full_name: str,
        user_id: str,
        phone: str,
        email: str,
        address: str,
        contacted_merchant: bool,
        purchase_date: str,
        issue_noticed_date: str,
        dispute_reason: str,
        resolution_requested: str,
        eligible_for_provisional_credit: bool,
        partial_refund_amount: Optional[float] = None,
    ) -> str:
        """File a formal dispute for a credit card transaction.

        Args:
            transaction_id (string): The unique identifier for the transaction being disputed
            card_action (string): Flag indicating the card's status. Must be one of: 'keep_active' (card remains active, dispute only), 'cancel_and_reissue' (card is being cancelled and replaced). This is for record-keeping only and does NOT order a replacement card.
            card_last_4_digits (string): Last 4 digits of the credit card number
            full_name (string): Full legal name of the cardholder
            user_id (string): The user's unique identifier in the system
            phone (string): Contact phone number
            email (string): Contact email address
            address (string): Contact mailing address
            contacted_merchant (boolean): Whether the user attempted to resolve the issue with the merchant first
            purchase_date (string): Date when the purchase was made, format MM/DD/YYYY
            issue_noticed_date (string): Date when the user noticed the issue, format MM/DD/YYYY
            dispute_reason (string): Reason for the dispute. Must be one of: 'unauthorized_fraudulent_charge', 'duplicate_charge', 'incorrect_amount', 'goods_services_not_received', 'goods_services_not_as_described', 'canceled_subscription_still_charging', 'refund_never_processed'
            resolution_requested (string): Resolution being requested. Must be one of: 'full_refund', 'partial_refund'
            eligible_for_provisional_credit (boolean): Whether the user is eligible for provisional credit
            partial_refund_amount (number, optional): Amount requested for partial refund (required only if resolution_requested is 'partial_refund')

        Returns:
            Credit card transaction dispute filed successfully. A case has been opened and will be reviewed within 10 business days.
        """
        if not transaction_id or not user_id:
            return "Error: Missing required parameters."

        # Validate card_action
        valid_card_actions = ["keep_active", "cancel_and_reissue"]
        if card_action not in valid_card_actions:
            return f"Error: Invalid card_action. Must be one of: {valid_card_actions}"

        # Validate dispute_reason
        valid_reasons = [
            "unauthorized_fraudulent_charge",
            "duplicate_charge",
            "incorrect_amount",
            "goods_services_not_received",
            "goods_services_not_as_described",
            "canceled_subscription_still_charging",
            "refund_never_processed",
        ]
        if dispute_reason not in valid_reasons:
            return f"Error: Invalid dispute_reason. Must be one of: {valid_reasons}"

        # Validate resolution_requested
        valid_resolutions = ["full_refund", "partial_refund"]
        if resolution_requested not in valid_resolutions:
            return f"Error: Invalid resolution_requested. Must be one of: {valid_resolutions}"

        # If partial refund, check for amount
        if resolution_requested == "partial_refund":
            if partial_refund_amount is None:
                return "Error: partial_refund_amount is required when resolution_requested is 'partial_refund'."

        # Generate a deterministic dispute ID
        dispute_id = generate_dispute_id(user_id, transaction_id)

        # Create the dispute record
        dispute_record = {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "user_id": user_id,
            "card_action": card_action,
            "card_last_4_digits": card_last_4_digits,
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "address": address,
            "contacted_merchant": contacted_merchant,
            "purchase_date": purchase_date,
            "issue_noticed_date": issue_noticed_date,
            "dispute_reason": dispute_reason,
            "resolution_requested": resolution_requested,
            "partial_refund_amount": partial_refund_amount,
            "eligible_for_provisional_credit": eligible_for_provisional_credit,
            "provisional_credit_given": eligible_for_provisional_credit,
            "submitted_at": get_today_str(),
            "status": "SUBMITTED",
        }

        # Add to the transaction_disputes table
        success = add_to_db(
            "transaction_disputes", dispute_id, dispute_record, db=self.db
        )

        if not success:
            return "Error: Dispute may have already been filed for this transaction."

        # Build response
        result_parts = [
            "Credit card transaction dispute filed successfully. A case has been opened and will be reviewed within 10 business days.",
            "",
            f"Executed: file_credit_card_transaction_dispute_4829",
            f"Dispute ID: {dispute_id}",
            f"Transaction: {transaction_id}",
            f"Reason: {dispute_reason.replace('_', ' ').title()}",
            f"Resolution Requested: {resolution_requested.replace('_', ' ').title()}",
        ]

        if partial_refund_amount:
            result_parts.append(f"Partial Refund Amount: ${partial_refund_amount:.2f}")

        if eligible_for_provisional_credit:
            result_parts.append(
                "Provisional Credit: ELIGIBLE - Credit will be applied within 2 business days."
            )
        else:
            result_parts.append("Provisional Credit: Not eligible at this time.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def file_debit_card_transaction_dispute_6281(
        self,
        transaction_id: str,
        account_id: str,
        card_id: str,
        user_id: str,
        dispute_category: str,
        transaction_date: str,
        discovery_date: str,
        disputed_amount: float,
        transaction_type: str,
        card_in_possession: bool,
        pin_compromised: str,
        contacted_merchant: bool,
        police_report_filed: bool,
        written_statement_provided: bool,
        provisional_credit_eligible: bool,
        customer_max_liability_amount: float,
        card_action: str,
    ) -> str:
        """File a formal dispute for a debit card transaction under Regulation E. Debit card disputes affect actual bank funds and have different liability rules based on reporting timing.

        Args:
            transaction_id (string): The unique identifier for the transaction being disputed
            account_id (string): The checking account ID linked to the debit card
            card_id (string): The debit card ID
            user_id (string): The user's unique identifier in the system
            dispute_category (string): Category of the dispute. Must be one of: 'unauthorized_transaction', 'atm_cash_discrepancy', 'atm_deposit_not_credited', 'duplicate_charge', 'incorrect_amount', 'goods_services_not_received', 'recurring_charge_after_cancellation', 'card_present_fraud', 'card_not_present_fraud'
            transaction_date (string): Date when the transaction occurred, format MM/DD/YYYY
            discovery_date (string): Date when the user first noticed the issue, format MM/DD/YYYY
            disputed_amount (number): The dollar amount being disputed
            transaction_type (string): Type of transaction. Must be one of: 'pin_purchase', 'signature_purchase', 'online_purchase', 'atm_withdrawal', 'atm_deposit', 'recurring_payment', 'person_to_person'
            card_in_possession (boolean): Whether the customer still has their physical debit card in their possession
            pin_compromised (string): Whether the customer's PIN may have been compromised. Must be one of: 'yes_shared', 'yes_observed', 'no', 'unknown'
            contacted_merchant (boolean): Whether the user attempted to resolve the issue with the merchant first
            police_report_filed (boolean): Whether a police report has been filed (recommended for fraud over $500)
            written_statement_provided (boolean): Whether the customer has provided a written statement describing what happened (required for Reg E provisional credit)
            provisional_credit_eligible (boolean): Whether the user is eligible for provisional credit based on Debit Card Provisional Credit Guidelines
            customer_max_liability_amount (number): The maximum dollar amount the customer could be liable for based on Regulation E reporting timing rules and the disputed amount. Use -1 for unlimited liability.
            card_action (string): Action to take on the card. Must be one of: 'keep_active', 'freeze_pending_investigation', 'close_and_reissue'

        Returns:
            Debit card transaction dispute filed successfully. A case has been opened and provisional credit determination has been recorded.
        """
        if not transaction_id or not account_id or not card_id or not user_id:
            return "Error: Missing required parameters."

        # Validate dispute_category
        valid_categories = [
            "unauthorized_transaction",
            "atm_cash_discrepancy",
            "atm_deposit_not_credited",
            "duplicate_charge",
            "incorrect_amount",
            "goods_services_not_received",
            "recurring_charge_after_cancellation",
            "card_present_fraud",
            "card_not_present_fraud",
        ]
        if dispute_category not in valid_categories:
            return (
                f"Error: Invalid dispute_category. Must be one of: {valid_categories}"
            )

        # Validate transaction_type
        valid_transaction_types = [
            "pin_purchase",
            "signature_purchase",
            "online_purchase",
            "atm_withdrawal",
            "atm_deposit",
            "recurring_payment",
            "person_to_person",
        ]
        if transaction_type not in valid_transaction_types:
            return f"Error: Invalid transaction_type. Must be one of: {valid_transaction_types}"

        # Validate pin_compromised
        valid_pin_statuses = ["yes_shared", "yes_observed", "no", "unknown"]
        if pin_compromised not in valid_pin_statuses:
            return (
                f"Error: Invalid pin_compromised. Must be one of: {valid_pin_statuses}"
            )

        # Validate card_action
        valid_card_actions = [
            "keep_active",
            "freeze_pending_investigation",
            "close_and_reissue",
        ]
        if card_action not in valid_card_actions:
            return f"Error: Invalid card_action. Must be one of: {valid_card_actions}"

        # Generate a deterministic dispute ID
        dispute_id = generate_dispute_id(user_id, transaction_id)

        # Create the debit card dispute record
        dispute_record = {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "account_id": account_id,
            "card_id": card_id,
            "user_id": user_id,
            "dispute_category": dispute_category,
            "transaction_date": transaction_date,
            "discovery_date": discovery_date,
            "disputed_amount": disputed_amount,
            "transaction_type": transaction_type,
            "card_in_possession": card_in_possession,
            "pin_compromised": pin_compromised,
            "contacted_merchant": contacted_merchant,
            "police_report_filed": police_report_filed,
            "written_statement_provided": written_statement_provided,
            "provisional_credit_eligible": provisional_credit_eligible,
            "provisional_credit_amount": disputed_amount
            if provisional_credit_eligible
            else 0,
            "customer_max_liability_amount": customer_max_liability_amount,
            "card_action": card_action,
            "submitted_at": get_today_str(),
            "status": "SUBMITTED",
            "investigation_deadline": None,
            "resolution_date": None,
        }

        # Add to the debit_card_disputes table
        success = add_to_db(
            "debit_card_disputes", dispute_id, dispute_record, db=self.db
        )

        if not success:
            return "Error: Dispute may have already been filed for this transaction."

        # Build response
        result_parts = [
            "Debit card transaction dispute filed successfully. A case has been opened and provisional credit determination has been recorded.",
            "",
            f"Executed: file_debit_card_transaction_dispute_6281",
            f"Dispute ID: {dispute_id}",
            f"Transaction: {transaction_id}",
            f"Category: {dispute_category.replace('_', ' ').title()}",
            f"Disputed Amount: ${disputed_amount:.2f}",
            f"Card Action: {card_action.replace('_', ' ').title()}",
        ]

        if provisional_credit_eligible:
            result_parts.append(
                f"Provisional Credit: ELIGIBLE - ${disputed_amount:.2f} to be credited within 10 business days."
            )
        else:
            result_parts.append("Provisional Credit: Not eligible at this time.")

        if customer_max_liability_amount == -1:
            result_parts.append(
                "Customer Liability: Unlimited (reported after 60 days)"
            )
        else:
            result_parts.append(
                f"Customer Max Liability: ${customer_max_liability_amount:.2f}"
            )

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def set_debit_card_recurring_block_7382(
        self,
        card_id: str,
        block_recurring: bool,
    ) -> str:
        """Block or unblock all recurring payments on a debit card. When blocked, all recurring/subscription charges will be declined. One-time purchases are not affected.

        Args:
            card_id (string): The debit card ID to update
            block_recurring (boolean): True to block all recurring payments, False to unblock/allow recurring payments

        Returns:
            Debit card recurring payment settings updated successfully.
        """
        if not card_id:
            return "Error: Missing required parameter: card_id"

        # Check if card exists
        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        # Update the card's recurring_block setting
        success, updated_record = update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"recurring_payments_blocked": block_recurring},
        )

        if not success:
            return f"Error: Failed to update debit card '{card_id}'."

        action = "blocked" if block_recurring else "unblocked"
        return (
            f"Debit card recurring payment settings updated successfully.\n\n"
            f"Executed: set_debit_card_recurring_block_7382\n"
            f"Arguments: {json.dumps({'card_id': card_id, 'block_recurring': block_recurring}, indent=2)}\n"
            f"Debit card {card_id}: Recurring payments are now {action}."
        )

    @is_discoverable_tool(ToolType.READ)
    def get_debit_dispute_status_7483(self, user_id: str) -> str:
        """Retrieve a user's debit card dispute history from the debit_card_disputes table. Returns all debit card disputes filed by the user, including dispute IDs, categories, amounts, statuses, and provisional credit information.

        Args:
            user_id (string): The user's unique identifier in the system

        Returns:
            Debit card dispute history retrieved successfully.
        """
        if not user_id:
            return "Error: Missing required parameter: user_id"

        debit_disputes_result = query_database_tool(
            "debit_card_disputes", f'{{"user_id": "{user_id}"}}', db=self.db
        )

        result_parts = [
            "Debit card dispute history retrieved successfully.",
            "",
            f"Executed: get_debit_dispute_status_7483",
            f"Debit card dispute history for user {user_id}:",
        ]

        has_disputes = (
            "No records found" not in debit_disputes_result
            and "No results found" not in debit_disputes_result
        )

        if has_disputes:
            result_parts.append(debit_disputes_result)
        else:
            result_parts.append("\nNo debit card disputes found for this user.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.READ)
    def get_atm_deposit_images_8473(self, transaction_id: str) -> str:
        """Retrieve ATM deposit envelope/check images for a specific ATM deposit transaction.

        Args:
            transaction_id (string): The transaction ID of the ATM deposit to retrieve images for

        Returns:
            ATM deposit images retrieved successfully.
        """
        if not transaction_id:
            return "Error: Missing required parameter: transaction_id"

        # Query the ATM deposit images table
        images_result = query_database_tool(
            "atm_deposit_images",
            f'{{"transaction_id": "{transaction_id}"}}',
            db=self.db,
        )

        result_parts = [
            "ATM deposit images retrieved successfully.",
            "",
            f"Executed: get_atm_deposit_images_8473",
            f"ATM deposit images for transaction {transaction_id}:",
        ]

        has_images = (
            "No records found" not in images_result
            and "No results found" not in images_result
        )

        if has_images:
            result_parts.append(images_result)
        else:
            result_parts.append(
                "\nNo ATM deposit images found for this transaction. Images may not be available for all ATM deposits."
            )

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def order_replacement_credit_card_7291(
        self,
        credit_card_account_id: str,
        user_id: str,
        shipping_address: str,
        reason: str,
        expedited_shipping: bool = False,
    ) -> str:
        """Order a replacement credit card for a customer. The old card will be automatically cancelled when the replacement is ordered.

        Args:
            credit_card_account_id (string): The credit card account ID for the card being replaced
            user_id (string): The user's unique identifier in the system
            shipping_address (string): Full shipping address where the new card should be sent
            reason (string): Reason for replacement. Must be one of: 'fraud_suspected', 'lost', 'stolen', 'damaged', 'expired', 'other'
            expedited_shipping (boolean, optional): Whether to use expedited shipping (2-3 business days instead of 7-10)

        Returns:
            Replacement credit card order placed successfully. The old card has been cancelled for security.
        """
        if (
            not credit_card_account_id
            or not user_id
            or not shipping_address
            or not reason
        ):
            return "Error: Missing required parameters (credit_card_account_id, user_id, shipping_address, reason)."

        valid_reasons = [
            "fraud_suspected",
            "lost",
            "stolen",
            "damaged",
            "expired",
            "other",
        ]
        if reason not in valid_reasons:
            return f"Error: Invalid reason. Must be one of: {valid_reasons}"

        # Verify credit card account exists
        result = query_database_tool(
            "credit_card_accounts",
            f'{{"account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        if "No results found" in result or "No records found" in result:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        # Generate order ID
        order_id = generate_credit_card_order_id(
            credit_card_account_id, user_id, reason
        )

        # Create the replacement order record
        today = get_today_str()
        order_record = {
            "order_id": order_id,
            "credit_card_account_id": credit_card_account_id,
            "user_id": user_id,
            "shipping_address": shipping_address,
            "reason": reason,
            "expedited_shipping": expedited_shipping,
            "order_date": today,
            "status": "ORDERED",
            "old_card_cancelled": True,
        }

        success = add_to_db("credit_card_orders", order_id, order_record, db=self.db)

        if not success:
            return f"Error: A replacement order may already exist for this account."

        shipping_time = (
            "2-3 business days" if expedited_shipping else "7-10 business days"
        )

        return (
            f"Replacement credit card order placed successfully. The old card has been cancelled for security.\n\n"
            f"Executed: order_replacement_credit_card_7291\n"
            f"Order ID: {order_id}\n"
            f"Account: {credit_card_account_id}\n"
            f"Reason: {reason.replace('_', ' ').title()}\n"
            f"Shipping: {shipping_address}\n"
            f"Expedited: {'Yes' if expedited_shipping else 'No'}\n"
            f"Estimated Arrival: {shipping_time}"
        )

    @is_discoverable_tool(ToolType.READ)
    def get_user_dispute_history_7291(self, user_id: str) -> str:
        """Retrieve a user's credit card transaction dispute history from the transaction_disputes table. Returns all credit card transaction disputes filed by the user, including dispute IDs, transaction IDs, dispute reasons, statuses, and submission dates.

        Args:
            user_id (string): The user's unique identifier in the system

        Returns:
            User transaction dispute history retrieved successfully.
        """
        if not user_id:
            return "Error: Missing required parameter: user_id"

        transaction_disputes_result = query_database_tool(
            "transaction_disputes", f'{{"user_id": "{user_id}"}}', db=self.db
        )

        result_parts = [
            "User transaction dispute history retrieved successfully.",
            "",
            f"Executed: get_user_dispute_history_7291",
            f"Transaction dispute history for user {user_id}:",
        ]

        has_disputes = (
            "No records found" not in transaction_disputes_result
            and "No results found" not in transaction_disputes_result
        )

        if has_disputes:
            result_parts.append(transaction_disputes_result)
        else:
            result_parts.append("\nNo transaction disputes found for this user.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.READ)
    def get_pending_replacement_orders_5765(self, credit_card_account_id: str) -> str:
        """Check if a credit card account has any pending replacement card orders.

        Args:
            credit_card_account_id (string): The credit card account ID to check for pending replacement orders

        Returns:
            Pending replacement orders check completed.
        """
        if not credit_card_account_id:
            return "Error: Missing required parameter: credit_card_account_id"

        orders_result = query_database_tool(
            "credit_card_orders",
            f'{{"credit_card_account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        result_parts = [
            "Pending replacement orders check completed.",
            "",
            f"Executed: get_pending_replacement_orders_5765",
            f"Replacement orders for credit card account {credit_card_account_id}:",
        ]

        has_orders = (
            "No records found" not in orders_result
            and "No results found" not in orders_result
        )

        if has_orders:
            result_parts.append(orders_result)
        else:
            result_parts.append(
                "\nNo pending replacement orders found for this credit card account."
            )

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def log_credit_card_closure_reason_4521(
        self,
        credit_card_account_id: str,
        user_id: str,
        closure_reason: str,
    ) -> str:
        """Log the reason why a customer wants to close their credit card account.

        Args:
            credit_card_account_id (string): The credit card account ID the customer wants to close
            user_id (string): The user's unique identifier in the system
            closure_reason (string): Reason for closure. Must be one of: 'annual_fee', 'not_using_card', 'found_better_card', 'unhappy_with_rewards', 'simplifying_finances', 'negative_experience', 'other'

        Returns:
            Closure reason logged successfully.
        """
        if not credit_card_account_id or not user_id or not closure_reason:
            return "Error: Missing required parameters."

        valid_reasons = [
            "annual_fee",
            "not_using_card",
            "found_better_card",
            "unhappy_with_rewards",
            "simplifying_finances",
            "negative_experience",
            "other",
        ]
        if closure_reason not in valid_reasons:
            return f"Error: Invalid closure_reason. Must be one of: {valid_reasons}"

        record_id = generate_closure_reason_id(credit_card_account_id, user_id)

        closure_record = {
            "record_id": record_id,
            "credit_card_account_id": credit_card_account_id,
            "user_id": user_id,
            "closure_reason": closure_reason,
            "logged_at": get_today_str(),
            "status": "LOGGED",
        }

        add_to_db("credit_card_closure_reasons", record_id, closure_record, db=self.db)

        return (
            f"Closure reason logged successfully.\n\n"
            f"Executed: log_credit_card_closure_reason_4521\n"
            f"Arguments: {json.dumps({'credit_card_account_id': credit_card_account_id, 'user_id': user_id, 'closure_reason': closure_reason}, indent=2)}\n"
            f"Closure reason '{closure_reason}' logged for account {credit_card_account_id}."
        )

    @is_discoverable_tool(ToolType.READ)
    def get_closure_reason_history_8293(self, credit_card_account_id: str) -> str:
        """Retrieve the closure reason history for a specific credit card account.

        Args:
            credit_card_account_id (string): The credit card account ID to check for previous closure attempts

        Returns:
            Closure reason history retrieved successfully.
        """
        if not credit_card_account_id:
            return "Error: Missing required parameter: credit_card_account_id"

        closure_reasons_result = query_database_tool(
            "credit_card_closure_reasons",
            f'{{"credit_card_account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        result_parts = [
            "Closure reason history retrieved successfully.",
            "",
            f"Executed: get_closure_reason_history_8293",
            f"Closure reason history for credit card account {credit_card_account_id}:",
        ]

        has_records = (
            "No records found" not in closure_reasons_result
            and "No results found" not in closure_reasons_result
        )

        if has_records:
            result_parts.append(closure_reasons_result)
        else:
            result_parts.append(
                "\nNo closure reason records found for this credit card account."
            )

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def apply_statement_credit_8472(
        self,
        user_id: str,
        credit_card_account_id: str,
        amount: float,
        reason: str,
    ) -> str:
        """Apply a statement credit to a customer's credit card account.

        Args:
            user_id (string): The user's unique identifier in the system
            credit_card_account_id (string): The credit card account ID to apply the credit to
            amount (number): The credit amount in dollars (e.g., 25.00 for a $25 credit)
            reason (string): Reason for the statement credit. Must be one of: 'goodwill_adjustment', 'promotional_credit', 'annual_fee_reversal', 'late_fee_reversal', 'interest_charge_reversal', 'dispute_resolution', 'price_match', 'retention_offer', 'error_correction', 'other'

        Returns:
            Statement credit applied successfully.
        """
        if not user_id or not credit_card_account_id or amount is None or not reason:
            return "Error: Missing required parameters (user_id, credit_card_account_id, amount, reason)."

        if amount <= 0:
            return "Error: Credit amount must be positive."

        valid_reasons = [
            "goodwill_adjustment",
            "promotional_credit",
            "annual_fee_reversal",
            "late_fee_reversal",
            "interest_charge_reversal",
            "dispute_resolution",
            "price_match",
            "retention_offer",
            "error_correction",
            "other",
        ]
        if reason not in valid_reasons:
            return f"Error: Invalid reason. Must be one of: {valid_reasons}"

        result = query_database_tool(
            "credit_card_accounts",
            f'{{"account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        if "No results found" in result or "No records found" in result:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        transaction_id = generate_transaction_id(
            user_id, "STATEMENT_CREDIT", reason, amount, "Statement Credit"
        )

        today = get_today_str()

        credit_record = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "credit_card_account_id": credit_card_account_id,
            "credit_card_type": "N/A",
            "merchant_name": "Rho-Bank Statement Credit",
            "transaction_amount": f"-${amount:.2f}",
            "transaction_date": today,
            "category": "Statement Credit",
            "status": "COMPLETED",
            "rewards_earned": "0 points",
            "credit_reason": reason,
        }

        success = add_to_db(
            "credit_card_transaction_history", transaction_id, credit_record, db=self.db
        )

        if not success:
            return f"Error: Failed to apply statement credit. Transaction ID '{transaction_id}' may already exist."

        return (
            f"Statement credit applied successfully.\n\n"
            f"Executed: apply_statement_credit_8472\n"
            f"  - Transaction ID: {transaction_id}\n"
            f"  - User ID: {user_id}\n"
            f"  - Account: {credit_card_account_id}\n"
            f"  - Credit Amount: ${amount:.2f}\n"
            f"  - Reason: {reason.replace('_', ' ').title()}\n"
            f"  - Date: {today}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def apply_credit_card_account_flag_6147(
        self,
        credit_card_account_id: str,
        user_id: str,
        flag_type: str,
        expiration_date: str,
        reason: str,
    ) -> str:
        """Apply a flag to a customer's credit card account. Flags can include annual fee waivers, promotional APR rates, rewards bonuses, or other account-level modifiers. Each flag has an effective date and expiration date.

        Args:
            credit_card_account_id (string): The credit card account ID to apply the flag to
            user_id (string): The user's unique identifier in the system
            flag_type (string): Type of flag to apply. Must be one of: 'annual_fee_waived', 'promotional_apr', 'rewards_bonus', 'other'
            expiration_date (string): Date when the flag expires (MM/DD/YYYY format)
            reason (string): Reason for applying this flag. Must be one of: 'retention_offer', 'loyalty_benefit', 'promotional', 'error_correction', 'other'

        Returns:
            Account flag applied successfully.
        """
        if (
            not credit_card_account_id
            or not user_id
            or not flag_type
            or not expiration_date
            or not reason
        ):
            return "Error: Missing required parameters (credit_card_account_id, user_id, flag_type, expiration_date, reason)."

        valid_flag_types = [
            "annual_fee_waived",
            "promotional_apr",
            "rewards_bonus",
            "other",
        ]
        if flag_type not in valid_flag_types:
            return f"Error: Invalid flag_type. Must be one of: {valid_flag_types}"

        valid_reasons = [
            "retention_offer",
            "loyalty_benefit",
            "promotional",
            "error_correction",
            "other",
        ]
        if reason not in valid_reasons:
            return f"Error: Invalid reason. Must be one of: {valid_reasons}"

        flag_id = generate_account_flag_id(
            credit_card_account_id, flag_type, expiration_date
        )

        today = get_today_str()

        flag_record = {
            "flag_id": flag_id,
            "credit_card_account_id": credit_card_account_id,
            "user_id": user_id,
            "flag_type": flag_type,
            "effective_date": today,
            "expiration_date": expiration_date,
            "reason": reason,
            "status": "ACTIVE",
        }

        success = add_to_db(
            "credit_card_account_flags", flag_id, flag_record, db=self.db
        )

        if not success:
            return f"Error: A similar flag may already exist for this account."

        return (
            f"Account flag applied successfully.\n\n"
            f"Executed: apply_credit_card_account_flag_6147\n"
            f"  - Flag ID: {flag_id}\n"
            f"  - Account: {credit_card_account_id}\n"
            f"  - Flag Type: {flag_type.replace('_', ' ').title()}\n"
            f"  - Effective: {today}\n"
            f"  - Expires: {expiration_date}\n"
            f"  - Reason: {reason.replace('_', ' ').title()}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def close_credit_card_account_7834(
        self,
        credit_card_account_id: str,
        user_id: str,
    ) -> str:
        """Close a customer's credit card account permanently.

        Args:
            credit_card_account_id (string): The credit card account ID to close
            user_id (string): The user's unique identifier in the system

        Returns:
            Credit card account closed successfully.
        """
        if not credit_card_account_id or not user_id:
            return (
                "Error: Missing required parameters (credit_card_account_id, user_id)."
            )

        result = query_database_tool(
            "credit_card_accounts",
            f'{{"account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        if "No results found" in result or "No records found" in result:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        success, updated_record = update_record_in_db(
            "credit_card_accounts",
            db=self.db,
            record_id=credit_card_account_id,
            updates={
                "status": "CLOSED",
                "closed_date": get_today_str(),
                "closed_by": user_id,
            },
        )

        if not success:
            return f"Error: Failed to close credit card account '{credit_card_account_id}'."

        return (
            f"Credit card account closed successfully.\n\n"
            f"Executed: close_credit_card_account_7834\n"
            f"Arguments: {json.dumps({'credit_card_account_id': credit_card_account_id, 'user_id': user_id}, indent=2)}\n"
            f"Account {credit_card_account_id} has been closed."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def pay_credit_card_from_checking_9182(
        self,
        user_id: str,
        checking_account_id: str,
        credit_card_account_id: str,
        amount: float,
    ) -> str:
        """Pay off a credit card balance using funds from the customer's Rho-Bank checking account. This deducts the specified amount from the checking account and reduces the credit card balance by the same amount.

        Args:
            user_id (string): The customer's unique identifier in the system
            checking_account_id (string): The ID of the Rho-Bank checking account to debit funds from
            credit_card_account_id (string): The ID of the credit card account to apply the payment to
            amount (number): The payment amount in dollars. Must be a positive number.

        Returns:
            Credit card payment processed successfully.
        """
        if (
            not user_id
            or not checking_account_id
            or not credit_card_account_id
            or amount is None
        ):
            return "Error: Missing required parameters."

        if amount <= 0:
            return "Error: Payment amount must be positive."

        # Verify checking account exists and has sufficient funds
        if checking_account_id not in self.db.accounts.data:
            return f"Error: Checking account '{checking_account_id}' not found."

        checking_account = self.db.accounts.data[checking_account_id]
        current_balance = _get_account_balance(checking_account)

        if current_balance < amount:
            return f"Error: Insufficient funds. Available balance: ${current_balance:.2f}, Payment amount: ${amount:.2f}"

        # Verify credit card account exists
        result = query_database_tool(
            "credit_card_accounts",
            f'{{"account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        if "No results found" in result or "No records found" in result:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        # Debit checking account
        new_checking_balance = current_balance - amount
        success, _ = update_record_in_db(
            "accounts",
            db=self.db,
            record_id=checking_account_id,
            updates={"current_holdings": f"{new_checking_balance:.2f}"},
        )

        if not success:
            return "Error: Failed to debit checking account."

        # Record the payment transaction
        transaction_id = generate_transaction_id(
            user_id, "CC_PAYMENT", credit_card_account_id, amount, "Credit Card Payment"
        )

        today = get_today_str()

        payment_record = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "credit_card_account_id": credit_card_account_id,
            "credit_card_type": "N/A",
            "merchant_name": "Credit Card Payment",
            "transaction_amount": f"-${amount:.2f}",
            "transaction_date": today,
            "category": "Payment",
            "status": "COMPLETED",
            "rewards_earned": "0 points",
            "payment_source": checking_account_id,
        }

        add_to_db(
            "credit_card_transaction_history",
            transaction_id,
            payment_record,
            db=self.db,
        )

        return (
            f"Credit card payment processed successfully.\n\n"
            f"Executed: pay_credit_card_from_checking_9182\n"
            f"  - Transaction ID: {transaction_id}\n"
            f"  - Payment Amount: ${amount:.2f}\n"
            f"  - From Checking: {checking_account_id}\n"
            f"  - To Credit Card: {credit_card_account_id}\n"
            f"  - Previous Checking Balance: ${current_balance:.2f}\n"
            f"  - New Checking Balance: ${new_checking_balance:.2f}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def submit_credit_limit_increase_request_7392(
        self,
        credit_card_account_id: str,
        user_id: str,
        requested_increase_amount: int,
    ) -> str:
        """Submit a credit limit increase request for a customer's credit card.

        Args:
            credit_card_account_id (string): The credit card account ID to request increase for
            user_id (string): The customer's unique identifier in the system
            requested_increase_amount (integer): The dollar amount by which to increase the credit limit (e.g., 2500 for $2,500)

        Returns:
            Credit limit increase request submitted successfully.
        """
        if (
            not credit_card_account_id
            or not user_id
            or requested_increase_amount is None
        ):
            return "Error: Missing required parameters."

        if requested_increase_amount <= 0:
            return "Error: Requested increase amount must be positive."

        request_id = generate_credit_limit_increase_request_id(
            credit_card_account_id, user_id, requested_increase_amount
        )

        today = get_today_str()

        request_record = {
            "request_id": request_id,
            "credit_card_account_id": credit_card_account_id,
            "user_id": user_id,
            "requested_increase_amount": requested_increase_amount,
            "submitted_at": today,
            "status": "PENDING",
        }

        success = add_to_db(
            "credit_limit_increase_requests", request_id, request_record, db=self.db
        )

        if not success:
            return "Error: A similar request may already exist."

        return (
            f"Credit limit increase request submitted successfully.\n\n"
            f"Executed: submit_credit_limit_increase_request_7392\n"
            f"  - Request ID: {request_id}\n"
            f"  - Account: {credit_card_account_id}\n"
            f"  - Requested Increase: ${requested_increase_amount:,}\n"
            f"  - Status: PENDING"
        )

    @is_discoverable_tool(ToolType.READ)
    def get_credit_limit_increase_history_4829(
        self, credit_card_account_id: str
    ) -> str:
        """Retrieve the credit limit increase request history for a specific credit card account. Returns all previous CLI requests including dates, amounts, and statuses.

        Args:
            credit_card_account_id (string): The credit card account ID to check for CLI history

        Returns:
            Credit limit increase history retrieved.
        """
        if not credit_card_account_id:
            return "Error: Missing required parameter: credit_card_account_id"

        cli_result = query_database_tool(
            "credit_limit_increase_requests",
            f'{{"credit_card_account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        result_parts = [
            "Credit limit increase history retrieved.",
            "",
            f"Executed: get_credit_limit_increase_history_4829",
            f"Credit limit increase history for account {credit_card_account_id}:",
        ]

        has_records = (
            "No records found" not in cli_result
            and "No results found" not in cli_result
        )

        if has_records:
            result_parts.append(cli_result)
        else:
            result_parts.append(
                "\nNo credit limit increase requests found for this account."
            )

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.READ)
    def get_payment_history_6183(self, credit_card_account_id: str, months: int) -> str:
        """Retrieve payment history for a credit card account.

        Args:
            credit_card_account_id (string): The credit card account ID to check payment history for
            months (integer): Number of months of payment history to retrieve

        Returns:
            Payment history retrieved.
        """
        if not credit_card_account_id or months is None:
            return "Error: Missing required parameters."

        payment_result = query_database_tool(
            "credit_card_transaction_history",
            f'{{"credit_card_account_id": "{credit_card_account_id}", "category": "Payment"}}',
            db=self.db,
        )

        result_parts = [
            "Payment history retrieved.",
            "",
            f"Executed: get_payment_history_6183",
            f"Payment history for account {credit_card_account_id} (last {months} months):",
        ]

        has_records = (
            "No records found" not in payment_result
            and "No results found" not in payment_result
        )

        if has_records:
            result_parts.append(payment_result)
        else:
            result_parts.append("\nNo payment records found for this account.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def approve_credit_limit_increase_5847(
        self,
        credit_card_account_id: str,
        user_id: str,
        new_credit_limit: int,
    ) -> str:
        """Approve and apply a credit limit increase for a customer's credit card.

        Args:
            credit_card_account_id (string): The credit card account ID
            user_id (string): The customer's unique identifier in the system
            new_credit_limit (integer): The new total credit limit in dollars (e.g., 7500 for $7,500)

        Returns:
            Credit limit increase approved and applied successfully.
        """
        if not credit_card_account_id or not user_id or new_credit_limit is None:
            return "Error: Missing required parameters."

        # Update the credit limit
        success, updated_record = update_record_in_db(
            "credit_card_accounts",
            db=self.db,
            record_id=credit_card_account_id,
            updates={"credit_limit": new_credit_limit},
        )

        if not success:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        return (
            f"Credit limit increase approved and applied successfully.\n\n"
            f"Executed: approve_credit_limit_increase_5847\n"
            f"  - Account: {credit_card_account_id}\n"
            f"  - New Credit Limit: ${new_credit_limit:,}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def deny_credit_limit_increase_5848(
        self,
        credit_card_account_id: str,
        user_id: str,
        denial_reason: str,
    ) -> str:
        """Deny a credit limit increase request for a customer's credit card.

        Args:
            credit_card_account_id (string): The credit card account ID
            user_id (string): The customer's unique identifier in the system
            denial_reason (string): The reason for denying the request. Must be one of: 'insufficient_income', 'recent_delinquency', 'account_too_new', 'high_utilization', 'recent_cli_granted', 'other'

        Returns:
            Credit limit increase request denied.
        """
        if not credit_card_account_id or not user_id or not denial_reason:
            return "Error: Missing required parameters."

        valid_reasons = [
            "insufficient_income",
            "recent_delinquency",
            "account_too_new",
            "high_utilization",
            "recent_cli_granted",
            "other",
        ]
        if denial_reason not in valid_reasons:
            return f"Error: Invalid denial_reason. Must be one of: {valid_reasons}"

        return (
            f"Credit limit increase request denied.\n\n"
            f"Executed: deny_credit_limit_increase_5848\n"
            f"  - Account: {credit_card_account_id}\n"
            f"  - Denial Reason: {denial_reason.replace('_', ' ').title()}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def open_bank_account_4821(
        self,
        user_id: str,
        account_type: str,
        account_class: str,
    ) -> str:
        """Open a new bank account for a customer.

        Args:
            user_id (string): The customer's unique identifier in the system
            account_type (string): Type of account to open. Must be one of: 'checking' (personal checking), 'savings' (personal savings), 'business_checking', 'business_savings'
            account_class (string): The full official account class name

        Returns:
            Bank account opened successfully.
        """
        if not user_id or not account_type or not account_class:
            return "Error: Missing required parameters."

        valid_types = ["checking", "savings", "business_checking", "business_savings"]
        if account_type not in valid_types:
            return f"Error: Invalid account_type. Must be one of: {valid_types}"

        # Generate account ID
        account_id = _deterministic_id(
            f"acct_{user_id}_{account_type}_{account_class}"
        )[:16]

        today = get_today_str()

        account_record = {
            "account_id": account_id,
            "user_id": user_id,
            "account_type": account_type,
            "account_class": account_class,
            "balance": 0.0,
            "status": "OPEN",
            "opened_date": today,
        }

        success = add_to_db("accounts", account_id, account_record, db=self.db)

        if not success:
            return "Error: Account may already exist."

        return (
            f"Bank account opened successfully.\n\n"
            f"Executed: open_bank_account_4821\n"
            f"  - Account ID: {account_id}\n"
            f"  - Type: {account_type}\n"
            f"  - Class: {account_class}\n"
            f"  - Status: OPEN"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def close_bank_account_7392(self, account_id: str) -> str:
        """Close a customer's bank account (checking or savings).

        Args:
            account_id (string): The ID of the bank account to close

        Returns:
            Bank account closed successfully.
        """
        if not account_id:
            return "Error: Missing required parameter: account_id"

        if account_id not in self.db.accounts.data:
            return f"Error: Account '{account_id}' not found."

        account = self.db.accounts.data[account_id]
        balance = _get_account_balance(account)

        if balance != 0:
            return f"Error: Account has a balance of ${balance:.2f}. Balance must be $0.00 to close."

        success, _ = update_record_in_db(
            "accounts",
            db=self.db,
            record_id=account_id,
            updates={"status": "CLOSED", "closed_date": get_today_str()},
        )

        if not success:
            return f"Error: Failed to close account '{account_id}'."

        return (
            f"Bank account closed successfully.\n\n"
            f"Executed: close_bank_account_7392\n"
            f"Account {account_id} has been closed."
        )

    @is_discoverable_tool(ToolType.READ)
    def get_all_user_accounts_by_user_id_3847(self, user_id: str) -> str:
        """Retrieve all accounts (checking, savings, credit cards) for a customer.

        Args:
            user_id (string): The customer's unique identifier in the system

        Returns:
            User accounts retrieved successfully.
        """
        if not user_id:
            return "Error: Missing required parameter: user_id"

        accounts_result = query_database_tool(
            "accounts", f'{{"user_id": "{user_id}"}}', db=self.db
        )

        cc_result = query_database_tool(
            "credit_card_accounts", f'{{"user_id": "{user_id}"}}', db=self.db
        )

        result_parts = [
            "User accounts retrieved successfully.",
            "",
            f"Executed: get_all_user_accounts_by_user_id_3847",
            f"Accounts for user {user_id}:",
            "",
            "Bank Accounts:",
        ]

        if (
            "No records found" not in accounts_result
            and "No results found" not in accounts_result
        ):
            result_parts.append(accounts_result)
        else:
            result_parts.append("  No bank accounts found.")

        result_parts.append("\nCredit Card Accounts:")
        if "No records found" not in cc_result and "No results found" not in cc_result:
            result_parts.append(cc_result)
        else:
            result_parts.append("  No credit card accounts found.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def transfer_funds_between_bank_accounts_7291(
        self,
        source_account_id: str,
        destination_account_id: str,
        amount: float,
    ) -> str:
        """Transfer funds from one bank account to another.

        Args:
            source_account_id (string): The account ID to transfer funds from
            destination_account_id (string): The account ID to transfer funds to
            amount (number): The amount to transfer in USD

        Returns:
            Funds transferred successfully.
        """
        if not source_account_id or not destination_account_id or amount is None:
            return "Error: Missing required parameters."

        if amount <= 0:
            return "Error: Transfer amount must be positive."

        if source_account_id not in self.db.accounts.data:
            return f"Error: Source account '{source_account_id}' not found."

        if destination_account_id not in self.db.accounts.data:
            return f"Error: Destination account '{destination_account_id}' not found."

        source = self.db.accounts.data[source_account_id]
        source_balance = _get_account_balance(source)

        if source_balance < amount:
            return f"Error: Insufficient funds. Available: ${source_balance:.2f}"

        dest = self.db.accounts.data[destination_account_id]
        dest_balance = _get_account_balance(dest)

        # Debit source
        new_source = source_balance - amount
        update_record_in_db(
            "accounts",
            db=self.db,
            record_id=source_account_id,
            updates={"current_holdings": f"{new_source:.2f}"},
        )

        # Credit destination
        new_dest = dest_balance + amount
        update_record_in_db(
            "accounts",
            db=self.db,
            record_id=destination_account_id,
            updates={"current_holdings": f"{new_dest:.2f}"},
        )

        return (
            f"Funds transferred successfully.\n\n"
            f"Executed: transfer_funds_between_bank_accounts_7291\n"
            f"  - Amount: ${amount:.2f}\n"
            f"  - From: {source_account_id} (New Balance: ${new_source:.2f})\n"
            f"  - To: {destination_account_id} (New Balance: ${new_dest:.2f})"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def apply_checking_account_credit_5829(
        self,
        account_id: str,
        amount: float,
        credit_type: str,
    ) -> str:
        """Apply a credit to a customer's checking account.

        Args:
            account_id (string): The checking account ID to credit
            amount (number): The positive dollar amount to credit (must be greater than 0)
            credit_type (string): The type of credit: 'rebate_credit' for missing rebates, 'fee_refund' for incorrect fee charges

        Returns:
            Credit applied to checking account successfully.
        """
        if not account_id or amount is None or not credit_type:
            return "Error: Missing required parameters."

        if amount <= 0:
            return "Error: Credit amount must be positive."

        valid_types = ["rebate_credit", "fee_refund"]
        if credit_type not in valid_types:
            return f"Error: Invalid credit_type. Must be one of: {valid_types}"

        if account_id not in self.db.accounts.data:
            return f"Error: Account '{account_id}' not found."

        account = self.db.accounts.data[account_id]
        current_balance = _get_account_balance(account)
        new_balance = current_balance + amount

        update_record_in_db(
            "accounts",
            db=self.db,
            record_id=account_id,
            updates={"current_holdings": f"{new_balance:.2f}"},
        )

        return (
            f"Credit applied to checking account successfully.\n\n"
            f"Executed: apply_checking_account_credit_5829\n"
            f"  - Account: {account_id}\n"
            f"  - Credit Amount: ${amount:.2f}\n"
            f"  - Credit Type: {credit_type.replace('_', ' ').title()}\n"
            f"  - New Balance: ${new_balance:.2f}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def apply_savings_account_credit_6831(
        self,
        account_id: str,
        amount: float,
        credit_type: str,
    ) -> str:
        """Apply a credit to a customer's savings account for interest corrections, fee refunds, or goodwill adjustments.

        Args:
            account_id (string): The savings account ID to credit
            amount (number): The positive dollar amount to credit (must be greater than 0)
            credit_type (string): The type of credit: 'interest_correction' for APY/interest calculation errors, 'fee_refund' for incorrect fee charges, 'goodwill_credit' for customer service gestures

        Returns:
            Credit applied to savings account successfully.
        """
        if not account_id or amount is None or not credit_type:
            return "Error: Missing required parameters."

        if amount <= 0:
            return "Error: Credit amount must be positive."

        valid_types = ["interest_correction", "fee_refund", "goodwill_credit"]
        if credit_type not in valid_types:
            return f"Error: Invalid credit_type. Must be one of: {valid_types}"

        if account_id not in self.db.accounts.data:
            return f"Error: Account '{account_id}' not found."

        account = self.db.accounts.data[account_id]
        current_balance = _get_account_balance(account)
        new_balance = current_balance + amount

        update_record_in_db(
            "accounts",
            db=self.db,
            record_id=account_id,
            updates={"current_holdings": f"{new_balance:.2f}"},
        )

        return (
            f"Credit applied to savings account successfully.\n\n"
            f"Executed: apply_savings_account_credit_6831\n"
            f"  - Account: {account_id}\n"
            f"  - Credit Amount: ${amount:.2f}\n"
            f"  - Credit Type: {credit_type.replace('_', ' ').title()}\n"
            f"  - New Balance: ${new_balance:.2f}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def submit_interest_discrepancy_report_7294(
        self,
        account_id: str,
        user_id: str,
        expected_apy: float,
        actual_apy: float,
        amount_difference: float,
    ) -> str:
        """Submit a report for interest calculation discrepancies to the backend team for investigation. Use this when the interest credited to a customer's account does not match expected APY calculations.

        Args:
            account_id (string): The savings account ID with the discrepancy
            user_id (string): The customer's unique identifier
            expected_apy (number): The APY percentage the customer should have received (e.g., 2.775 for 2.775%)
            actual_apy (number): The APY percentage that was actually applied (e.g., 2.5 for 2.5%)
            amount_difference (number): The dollar amount difference between expected and actual interest credited

        Returns:
            Interest discrepancy report submitted successfully. Backend team will investigate.
        """
        if (
            not account_id
            or not user_id
            or expected_apy is None
            or actual_apy is None
            or amount_difference is None
        ):
            return "Error: Missing required parameters."

        report_id = _deterministic_id(
            f"interest_report_{account_id}_{user_id}_{expected_apy}_{actual_apy}"
        )[:16]

        report_record = {
            "report_id": report_id,
            "account_id": account_id,
            "user_id": user_id,
            "expected_apy": expected_apy,
            "actual_apy": actual_apy,
            "amount_difference": amount_difference,
            "submitted_at": get_today_str(),
            "status": "SUBMITTED",
        }

        add_to_db("interest_discrepancy_reports", report_id, report_record, db=self.db)

        return (
            f"Interest discrepancy report submitted successfully. Backend team will investigate.\n\n"
            f"Executed: submit_interest_discrepancy_report_7294\n"
            f"  - Report ID: {report_id}\n"
            f"  - Account: {account_id}\n"
            f"  - Expected APY: {expected_apy}%\n"
            f"  - Actual APY: {actual_apy}%\n"
            f"  - Difference: ${amount_difference:.2f}"
        )

    @is_discoverable_tool(ToolType.READ)
    def get_bank_account_transactions_9173(self, account_id: str) -> str:
        """Retrieve the transaction history for a bank account.

        Args:
            account_id (string): The bank account ID to retrieve transactions for

        Returns:
            Bank account transactions retrieved successfully.
        """
        if not account_id:
            return "Error: Missing required parameter: account_id"

        txn_result = query_database_tool(
            "bank_account_transaction_history",
            f'{{"account_id": "{account_id}"}}',
            db=self.db,
        )

        result_parts = [
            "Bank account transactions retrieved successfully.",
            "",
            f"Executed: get_bank_account_transactions_9173",
            f"Transactions for account {account_id}:",
        ]

        if (
            "No records found" not in txn_result
            and "No results found" not in txn_result
        ):
            result_parts.append(txn_result)
        else:
            result_parts.append("\nNo transactions found for this account.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def order_debit_card_5739(
        self,
        account_id: str,
        user_id: str,
        delivery_option: str,
        delivery_fee: float,
        card_design: str,
        design_fee: float,
        shipping_address: str,
        excess_replacement_fee: Optional[float] = None,
    ) -> str:
        """Order a new debit card for a customer's checking account.

        Args:
            account_id (string): The checking account ID to link the debit card to
            user_id (string): The customer's unique identifier
            delivery_option (string): Shipping speed: STANDARD, EXPEDITED, or RUSH
            delivery_fee (number): Fee to charge for delivery in dollars
            card_design (string): Card design: CLASSIC, PREMIUM, or CUSTOM
            design_fee (number): Fee to charge for card design in dollars
            shipping_address (string): Full shipping address for card delivery
            excess_replacement_fee (number, optional): Fee for exceeding replacement limit, if applicable

        Returns:
            Debit card order placed successfully.
        """
        if (
            not account_id
            or not user_id
            or not delivery_option
            or not card_design
            or not shipping_address
        ):
            return "Error: Missing required parameters."

        valid_delivery = ["STANDARD", "EXPEDITED", "RUSH"]
        if delivery_option not in valid_delivery:
            return f"Error: Invalid delivery_option. Must be one of: {valid_delivery}"

        valid_design = ["CLASSIC", "PREMIUM", "CUSTOM"]
        if card_design not in valid_design:
            return f"Error: Invalid card_design. Must be one of: {valid_design}"

        order_date = get_today_str()
        card_id = generate_debit_card_id(account_id, user_id, order_date)
        order_id = generate_debit_card_order_id(account_id, user_id, delivery_option)

        # Generate last 4 digits
        last_4 = _deterministic_id(f"card_{card_id}")[:4].upper()
        while not last_4.isdigit():
            last_4 = str(hash(last_4) % 10000).zfill(4)

        card_record = {
            "card_id": card_id,
            "account_id": account_id,
            "user_id": user_id,
            "last_4_digits": last_4,
            "status": "PENDING",
            "issue_reason": "new_account",
            "date_issued": get_today_str(),
            "delivery_option": delivery_option,
            "card_design": card_design,
            "shipping_address": shipping_address,
        }

        add_to_db("debit_cards", card_id, card_record, db=self.db)

        total_fee = delivery_fee + design_fee + (excess_replacement_fee or 0)

        return (
            f"Debit card order placed successfully.\n\n"
            f"Executed: order_debit_card_5739\n"
            f"  - Order ID: {order_id}\n"
            f"  - Card ID: {card_id}\n"
            f"  - Last 4: {last_4}\n"
            f"  - Account: {account_id}\n"
            f"  - Delivery: {delivery_option} (${delivery_fee:.2f})\n"
            f"  - Design: {card_design} (${design_fee:.2f})\n"
            f"  - Total Fees: ${total_fee:.2f}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def activate_debit_card_8291(
        self,
        card_id: str,
        last_4_digits: str,
        expiration_date: str,
        cvv: str,
        pin: str,
    ) -> str:
        """Activate a NEW debit card for a customer. Use ONLY for first-time cards on a checking account (issue_reason = 'new_account' or 'first_card'). For replacement or reissued cards, use the appropriate variant.

        Args:
            card_id (string): The debit card ID to activate
            last_4_digits (string): Last 4 digits of the card number (for verification)
            expiration_date (string): Card expiration date in MM/YY format
            cvv (string): 3-digit CVV from the back of the card
            pin (string): 4-digit PIN chosen by the customer

        Returns:
            New debit card activated successfully.
        """
        args = {
            "card_id": card_id,
            "last_4_digits": last_4_digits,
            "expiration_date": expiration_date,
            "cvv": cvv,
            "pin": pin,
        }

        error, card = _validate_activation_common(
            args, self.db, ["new_account", "first_card"], "activate_debit_card_8291"
        )
        if error:
            return error

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"status": "ACTIVE", "activated_date": get_today_str()},
        )

        return (
            f"New debit card activated successfully.\n\n"
            f"Executed: activate_debit_card_8291\n"
            f"Card {card_id} is now active."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def activate_debit_card_8292(
        self,
        card_id: str,
        last_4_digits: str,
        expiration_date: str,
        cvv: str,
        pin: str,
    ) -> str:
        """Activate a REPLACEMENT debit card. Use ONLY for cards replacing lost, stolen, or fraud-suspected cards (issue_reason = 'lost', 'stolen', or 'fraud'). For new or reissued cards, use the appropriate variant.

        Args:
            card_id (string): The debit card ID to activate
            last_4_digits (string): Last 4 digits of the card number (for verification)
            expiration_date (string): Card expiration date in MM/YY format
            cvv (string): 3-digit CVV from the back of the card
            pin (string): 4-digit PIN chosen by the customer

        Returns:
            Replacement debit card activated successfully.
        """
        args = {
            "card_id": card_id,
            "last_4_digits": last_4_digits,
            "expiration_date": expiration_date,
            "cvv": cvv,
            "pin": pin,
        }

        error, card = _validate_activation_common(
            args, self.db, ["lost", "stolen", "fraud"], "activate_debit_card_8292"
        )
        if error:
            return error

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"status": "ACTIVE", "activated_date": get_today_str()},
        )

        return (
            f"Replacement debit card activated successfully.\n\n"
            f"Executed: activate_debit_card_8292\n"
            f"Card {card_id} is now active."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def activate_debit_card_8293(
        self,
        card_id: str,
        last_4_digits: str,
        expiration_date: str,
        cvv: str,
        pin: str,
    ) -> str:
        """Activate a REISSUED debit card. Use ONLY for cards reissued due to expiration, damage, design upgrade, or bank-initiated replacement (issue_reason = 'expired', 'damaged', 'upgrade', or 'bank_reissue'). For new or replacement cards, use the appropriate variant.

        Args:
            card_id (string): The debit card ID to activate
            last_4_digits (string): Last 4 digits of the card number (for verification)
            expiration_date (string): Card expiration date in MM/YY format
            cvv (string): 3-digit CVV from the back of the card
            pin (string): 4-digit PIN chosen by the customer

        Returns:
            Reissued debit card activated successfully.
        """
        args = {
            "card_id": card_id,
            "last_4_digits": last_4_digits,
            "expiration_date": expiration_date,
            "cvv": cvv,
            "pin": pin,
        }

        error, card = _validate_activation_common(
            args,
            self.db,
            ["expired", "damaged", "upgrade", "bank_reissue"],
            "activate_debit_card_8293",
        )
        if error:
            return error

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"status": "ACTIVE", "activated_date": get_today_str()},
        )

        return (
            f"Reissued debit card activated successfully.\n\n"
            f"Executed: activate_debit_card_8293\n"
            f"Card {card_id} is now active."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def close_debit_card_4721(self, card_id: str, reason: str) -> str:
        """Close or cancel a debit card permanently.

        Args:
            card_id (string): The debit card ID to close
            reason (string): Reason for closing: lost, stolen, fraud_suspected, damaged, no_longer_needed, or account_closing

        Returns:
            Debit card closed successfully.
        """
        if not card_id or not reason:
            return "Error: Missing required parameters."

        valid_reasons = [
            "lost",
            "stolen",
            "fraud_suspected",
            "damaged",
            "no_longer_needed",
            "account_closing",
        ]
        if reason not in valid_reasons:
            return f"Error: Invalid reason. Must be one of: {valid_reasons}"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={
                "status": "CLOSED",
                "closed_date": get_today_str(),
                "close_reason": reason,
            },
        )

        return (
            f"Debit card closed successfully.\n\n"
            f"Executed: close_debit_card_4721\n"
            f"Card {card_id} has been closed. Reason: {reason}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def freeze_debit_card_3892(self, card_id: str) -> str:
        """Temporarily freeze a debit card. The card can be unfrozen later.

        Args:
            card_id (string): The debit card ID to freeze

        Returns:
            Debit card frozen successfully.
        """
        if not card_id:
            return "Error: Missing required parameter: card_id"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"status": "FROZEN", "frozen_date": get_today_str()},
        )

        return (
            f"Debit card frozen successfully.\n\n"
            f"Executed: freeze_debit_card_3892\n"
            f"Card {card_id} is now frozen. All transactions will be declined."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def unfreeze_debit_card_3893(self, card_id: str) -> str:
        """Unfreeze a previously frozen debit card.

        Args:
            card_id (string): The debit card ID to unfreeze

        Returns:
            Debit card unfrozen successfully.
        """
        if not card_id:
            return "Error: Missing required parameter: card_id"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        card = self.db.debit_cards.data[card_id]
        if card.get("status") != "FROZEN":
            return f"Error: Card is not frozen. Current status: {card.get('status')}"

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={"status": "ACTIVE", "unfrozen_date": get_today_str()},
        )

        return (
            f"Debit card unfrozen successfully.\n\n"
            f"Executed: unfreeze_debit_card_3893\n"
            f"Card {card_id} is now active again."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def clear_debit_card_fraud_alert_4892(self, card_id: str, reason: str) -> str:
        """Clear a fraud alert or velocity block on a debit card.

        Args:
            card_id (string): The debit card ID to clear the alert/block for
            reason (string): Reason for clearing: 'customer_verified' (for fraud alerts after customer verification) or 'velocity_clear' (for velocity blocks after identity verification)

        Returns:
            Fraud alert/velocity block cleared successfully.
        """
        if not card_id or not reason:
            return "Error: Missing required parameters."

        valid_reasons = ["customer_verified", "velocity_clear"]
        if reason not in valid_reasons:
            return f"Error: Invalid reason. Must be one of: {valid_reasons}"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        update_record_in_db(
            "debit_cards",
            db=self.db,
            record_id=card_id,
            updates={
                "fraud_alert": False,
                "velocity_block": False,
                "alert_cleared_date": get_today_str(),
            },
        )

        return (
            f"Fraud alert/velocity block cleared successfully.\n\n"
            f"Executed: clear_debit_card_fraud_alert_4892\n"
            f"Card {card_id} alerts cleared. Reason: {reason}"
        )

    @is_discoverable_tool(ToolType.WRITE)
    def reset_debit_card_pin_6284(
        self,
        card_id: str,
        last_4_digits: str,
        new_pin: str,
    ) -> str:
        """Reset a debit card PIN when the customer has forgotten it.

        Args:
            card_id (string): The debit card ID to reset PIN for
            last_4_digits (string): Last 4 digits of the card number (for verification)
            new_pin (string): The new 4-digit PIN chosen by the customer

        Returns:
            Debit card PIN reset successfully.
        """
        if not card_id or not last_4_digits or not new_pin:
            return "Error: Missing required parameters."

        pin_error = _validate_pin(new_pin)
        if pin_error:
            return f"Error: {pin_error}"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        card = self.db.debit_cards.data[card_id]
        if card.get("last_4_digits") != last_4_digits:
            return "Error: Last 4 digits do not match."

        return (
            f"Debit card PIN reset successfully.\n\n"
            f"Executed: reset_debit_card_pin_6284\n"
            f"PIN has been reset for card {card_id}."
        )

    @is_discoverable_tool(ToolType.WRITE)
    def change_debit_card_pin_6285(
        self,
        card_id: str,
        current_pin: str,
        new_pin: str,
    ) -> str:
        """Change a debit card PIN when the customer knows their current PIN.

        Args:
            card_id (string): The debit card ID to change PIN for
            current_pin (string): The customer's current 4-digit PIN
            new_pin (string): The new 4-digit PIN chosen by the customer

        Returns:
            Debit card PIN changed successfully.
        """
        if not card_id or not current_pin or not new_pin:
            return "Error: Missing required parameters."

        pin_error = _validate_pin(new_pin)
        if pin_error:
            return f"Error: {pin_error}"

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        return (
            f"Debit card PIN changed successfully.\n\n"
            f"Executed: change_debit_card_pin_6285\n"
            f"PIN has been changed for card {card_id}."
        )

    @is_discoverable_tool(ToolType.READ)
    def get_debit_cards_by_account_id_7823(self, account_id: str) -> str:
        """Retrieve all debit cards associated with a checking account. Returns card details including status, issue reason, and expiration date.

        Args:
            account_id (string): The checking account ID to retrieve debit cards for

        Returns:
            Debit cards retrieved successfully.
        """
        if not account_id:
            return "Error: Missing required parameter: account_id"

        # Filter debit cards by account_id
        account_cards = [
            card
            for card in self.db.debit_cards.data.values()
            if card.get("account_id") == account_id
        ]

        result_parts = [
            "Debit cards retrieved successfully.",
            "",
            f"Executed: get_debit_cards_by_account_id_7823",
            f"Debit cards for account {account_id}:",
        ]

        if account_cards:
            result_parts.append(json.dumps(account_cards, indent=2))
        else:
            result_parts.append("\nNo debit cards found for this account.")

        return "\n".join(result_parts)

    @is_discoverable_tool(ToolType.WRITE)
    def request_temporary_debit_card_limit_increase_8374(
        self,
        card_id: str,
        limit_type: str,
        new_limit: int,
    ) -> str:
        """Request a temporary 24-hour increase to a debit card's daily ATM or purchase limit.

        Args:
            card_id (string): The debit card ID to increase limits for
            limit_type (string): Type of limit to increase: 'atm' for daily ATM withdrawal limit, 'purchase' for daily purchase limit
            new_limit (integer): The requested new temporary limit amount in dollars

        Returns:
            Temporary limit increase granted successfully.
        """
        if not card_id or not limit_type or new_limit is None:
            return "Error: Missing required parameters."

        valid_types = ["atm", "purchase"]
        if limit_type not in valid_types:
            return f"Error: Invalid limit_type. Must be one of: {valid_types}"

        if new_limit <= 0:
            return "Error: New limit must be positive."

        if card_id not in self.db.debit_cards.data:
            return f"Error: Debit card '{card_id}' not found."

        return (
            f"Temporary limit increase granted successfully.\n\n"
            f"Executed: request_temporary_debit_card_limit_increase_8374\n"
            f"  - Card: {card_id}\n"
            f"  - Limit Type: {limit_type.upper()}\n"
            f"  - New Limit: ${new_limit:,}\n"
            f"  - Duration: 24 hours"
        )


class KnowledgeUserTools(ToolKitBase):
    """Tools available to the user (customer) in the knowledge domain.

    The `db` attribute is the TransactionalDB which is used for DB state
    hashing during evaluation.
    """

    db: TransactionalDB

    def __init__(
        self,
        db: TransactionalDB,
    ) -> None:
        super().__init__(db)

    def _check_tool_given(self, tool_name: str) -> Optional[str]:
        """Check if a user discoverable tool was given by the agent.

        Returns None if tool was given, or an error message if not.
        """
        result = query_database_tool(
            "user_discoverable_tools", f'{{"tool_name": "{tool_name}"}}', db=self.db
        )
        if "No records found" in result:
            return (
                f"Error: Tool '{tool_name}' has not been given to you by the agent. "
                f"The agent must first use `give_discoverable_user_tool` to give this tool to you."
            )
        return None

    def _log_user_tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Log a user discoverable tool call to the database."""
        call_record = {
            "tool_name": tool_name,
            "arguments": args,
            "called_at": get_today_str(),
            "status": "CALLED",
        }
        call_record_id = generate_user_discoverable_tool_call_id(tool_name, args)
        add_to_db(
            "user_discoverable_tool_calls", call_record_id, call_record, db=self.db
        )

    # =========================================================================
    # User Discoverable Tools
    # These tools represent actions users take in the real world. The agent
    # gives them to the user via give_discoverable_user_tool, and the user
    # calls them directly. They are NOT included in the default tool list.
    # =========================================================================

    @is_discoverable_tool(ToolType.WRITE)
    def submit_cash_back_dispute_0589(self, user_id: str, transaction_id: str) -> str:
        """Submit a cash back dispute for a specific transaction.

        Args:
            user_id (string): The user's unique identifier in the system
            transaction_id (string): The unique identifier for the transaction with incorrect cash back

        Returns:
            Cash back dispute submitted successfully. Your case has been queued for review.
        """
        error = self._check_tool_given("submit_cash_back_dispute_0589")
        if error:
            return error

        args = {"user_id": user_id, "transaction_id": transaction_id}
        self._log_user_tool_call("submit_cash_back_dispute_0589", args)

        # Business logic from _handle_submit_cash_back_dispute
        dispute_id = generate_dispute_id(user_id, transaction_id)

        auto_resolve = False
        if hasattr(self.db, "task_config") and self.db.task_config.data:
            config = self.db.task_config.data.get("dispute_settings", {})
            auto_resolve = config.get("auto_resolve_disputes", False)

        if auto_resolve:
            dispute_record = {
                "dispute_id": dispute_id,
                "user_id": user_id,
                "transaction_id": transaction_id,
                "submitted_at": get_today_str(),
                "status": "RESOLVED",
                "resolution": "APPROVED",
            }
            status_msg = "Status: RESOLVED - The dispute has been reviewed and approved. The transaction rewards need to be updated."
        else:
            dispute_record = {
                "dispute_id": dispute_id,
                "user_id": user_id,
                "transaction_id": transaction_id,
                "submitted_at": get_today_str(),
                "status": "SUBMITTED",
            }
            status_msg = "Status: SUBMITTED - Your dispute has been queued for review."

        success = add_to_db(
            "cash_back_disputes", dispute_id, dispute_record, db=self.db
        )

        result = f"Cash back dispute submitted successfully. Your case has been queued for review.\n\nExecuted: submit_cash_back_dispute_0589\nArguments: {json.dumps(args, indent=2)}\n"
        if success:
            result += f"Dispute ID: {dispute_id}\n{status_msg}"
        else:
            result += (
                "Note: Dispute may have already been submitted for this transaction."
            )

        return result

    @is_discoverable_tool(ToolType.WRITE)
    def get_referral_link(self, user_id: str, card_name: str) -> str:
        """Generate a referral link for a specific credit card to share with friends or family.

        Args:
            user_id (string): The user's unique identifier in the system (the referrer)
            card_name (string): The name of the credit card to create a referral for (e.g., 'Gold Rewards Card')

        Returns:
            Referral link generated successfully. Share this link with the person you want to refer.
        """
        error = self._check_tool_given("get_referral_link")
        if error:
            return error

        args = {"user_id": user_id, "card_name": card_name}
        self._log_user_tool_call("get_referral_link", args)

        # Business logic from _handle_get_referral_link
        referral_id = generate_referral_link_id(user_id, card_name)

        referral_record = {
            "referral_id": referral_id,
            "referrer_id": user_id,
            "referred_account_type": card_name,
            "referral_status": "NO_PROGRESS",
            "date": get_today_str(),
        }

        success = add_to_db("referrals", referral_id, referral_record, db=self.db)

        result = f"Referral link generated successfully. Share this link with the person you want to refer.\n\nExecuted: get_referral_link\nArguments: {json.dumps(args, indent=2)}\n"
        if success:
            result += f"Referral ID: {referral_id}\nReferral link: https://rhobank.com/refer/{referral_id}"
        else:
            result += (
                "Note: A referral link for this card may have already been generated."
            )

        return result

    @is_discoverable_tool(ToolType.READ)
    def get_card_last_4_digits(self, credit_card_account_id: str) -> str:
        """Look up the last 4 digits of a credit card number.

        Args:
            credit_card_account_id (string): The credit card account ID to look up (e.g., 'cc_76ad9cc60e_gold')

        Returns:
            Card information retrieved successfully.
        """
        error = self._check_tool_given("get_card_last_4_digits")
        if error:
            return error

        args = {"credit_card_account_id": credit_card_account_id}
        self._log_user_tool_call("get_card_last_4_digits", args)

        # Business logic from _handle_get_card_last_4_digits
        result = query_database_tool(
            "credit_card_accounts",
            f'{{"account_id": "{credit_card_account_id}"}}',
            db=self.db,
        )

        if "No results found" in result or "No records found" in result:
            return f"Error: Credit card account '{credit_card_account_id}' not found."

        import hashlib

        hash_input = f"card_last4:{credit_card_account_id}"
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()
        last_4 = ""
        for char in hash_digest:
            if char.isdigit():
                last_4 += char
                if len(last_4) == 4:
                    break
        last_4 = last_4.ljust(4, "0")

        return f"Card information retrieved successfully.\n\nExecuted: get_card_last_4_digits\nArguments: {json.dumps(args, indent=2)}\nLast 4 digits of card: {last_4}"

    @is_discoverable_tool(ToolType.WRITE)
    def deposit_check_3847(self, account_id: str, check_amount: float) -> str:
        """Deposit a check into a checking or savings account. The user takes a photo of the check and submits it through their mobile banking app.

        Args:
            account_id (string): The bank account ID to deposit the check into
            check_amount (number): The amount of the check in USD

        Returns:
            Check deposited successfully. Funds will be available according to your account's deposit policy.
        """
        error = self._check_tool_given("deposit_check_3847")
        if error:
            return error

        args = {"account_id": account_id, "check_amount": check_amount}
        self._log_user_tool_call("deposit_check_3847", args)

        # Business logic from _handle_deposit_check
        try:
            check_amount = float(check_amount)
        except (ValueError, TypeError):
            return f"Error: Invalid check amount '{check_amount}'. Must be a number."

        if check_amount <= 0:
            return "Error: Check amount must be positive."

        if account_id not in self.db.accounts.data:
            return f"Error: Account '{account_id}' not found."

        account = self.db.accounts.data[account_id]

        if account.get("status") not in ("ACTIVE", "OPEN"):
            return f"Error: Account '{account_id}' is not active."

        def parse_balance(val: Any) -> float:
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                return float(val.replace("$", "").replace(",", ""))
            return 0.0

        current_balance = parse_balance(
            account.get("current_holdings", account.get("balance", 0))
        )
        new_balance = current_balance + check_amount

        self.db.accounts.data[account_id]["current_holdings"] = f"${new_balance:.2f}"

        return (
            f"Check deposited successfully. Funds will be available according to your account's deposit policy.\n\n"
            f"Executed: deposit_check_3847\n"
            f"Arguments: {json.dumps(args, indent=2)}\n"
            f"Check deposit processed!\n"
            f"  - Account: {account_id}\n"
            f"  - Check Amount: ${check_amount:.2f}\n"
            f"  - Previous Balance: ${current_balance:.2f}\n"
            f"  - New Balance: ${new_balance:.2f}"
        )

    @is_tool(ToolType.WRITE)
    def apply_for_credit_card(
        self,
        card_type: str,
        customer_name: str,
        annual_income: float,
        rho_bank_subscription: bool = False,
    ) -> str:
        """Apply for a credit card.

        Args:
            card_type: Type of credit card
            customer_name: Full legal name
            annual_income: Annual income in USD
            rho_bank_subscription: Whether user has Rho-Bank+ subscription
        """
        # Generate a deterministic application ID from the input parameters
        # This ensures the same inputs produce the same ID for environment evaluation
        application_id = generate_application_id(
            card_type, customer_name, annual_income, rho_bank_subscription
        )

        # Get today's date in MM/DD/YYYY format
        today = get_today_str()

        # Create the application record
        record = {
            "application_id": application_id,
            "card_type": card_type,
            "customer_name": customer_name,
            "annual_income": annual_income,
            "rho_bank_subscription": rho_bank_subscription,
            "status": "PENDING",
            "date": today,
        }

        # Add to the credit_card_applications table (in-memory via db_query)
        success = add_to_db(
            "credit_card_applications", application_id, record, db=self.db
        )

        if not success:
            return f"Failed to submit application: Record ID '{application_id}' may already exist."

        return (
            f"Credit card application submitted:\n"
            f"Your application has been successfully submitted. "
            f"You will receive a decision within 5-7 business days via email."
        )

    @is_tool(ToolType.WRITE)
    def submit_referral(self, user_id: str, account_type: str) -> str:
        """Submit a referral request to refer someone to open an account.

        Args:
            user_id: Your user ID (the referrer)
            account_type: The type of account you are referring someone to open
        """
        # Generate a deterministic 16-character hex referral ID from the input parameters
        # This ensures the same inputs produce the same ID for environment evaluation
        referral_id = generate_referral_id(user_id, account_type)

        # Get today's date in MM/DD/YYYY format
        today = get_today_str()

        # Create the referral record
        record = {
            "referral_id": referral_id,
            "referrer_id": user_id,
            "referred_account_type": account_type,
            "referral_status": "NO_PROGRESS",
            "date": today,
        }

        # Add to the referrals table (in-memory via db_query)
        success = add_to_db("referrals", referral_id, record, db=self.db)

        if not success:
            return f"Failed to submit referral: Record ID '{referral_id}' may already exist."

        return (
            f"Referral request submitted successfully!\n"
            f"  - Referral ID: {referral_id}\n"
            f"  - Referrer ID: {user_id}\n"
            f"  - Account Type: {account_type}\n"
            f"  - Status: NO_PROGRESS\n"
            f"  - Date: {today}\n\n"
            f"Share your referral ID with the person you're referring. "
            f"They will need to use this when applying for their account."
        )

    def query_database(self, database_name: str, constraints: str = "{}") -> str:
        """Query a database with constraints.

        Args:
            database_name: Name of the database to query
            constraints: JSON string of field constraints
        """
        return query_database_tool(database_name, constraints, db=self.db)

    @is_tool(ToolType.WRITE)
    def call_discoverable_user_tool(
        self, discoverable_tool_name: str, arguments: str = "{}"
    ) -> str:
        """Call a tool that was given to you by the agent.

        Use this when the agent has instructed you to perform an action using
        a discoverable tool. The agent will have told you the tool name and arguments.

        This simulates you performing the action in the real world (e.g., opening
        a webpage, navigating to a section, clicking a button).

        Args:
            discoverable_tool_name: The name of the discoverable tool to call (e.g., "open_webpage")
            arguments: JSON string of arguments for the tool (e.g., '{"url": "https://example.com"}')

        Returns:
            The result of executing the discoverable tool
        """
        # Check if the tool exists as a discoverable method
        if not self.has_discoverable_tool(discoverable_tool_name):
            return f"Error: Unknown discoverable tool '{discoverable_tool_name}'."

        # Parse arguments
        try:
            args_dict = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in arguments: {e}"

        # Get the method and validate arguments against method signature
        method = self.get_discoverable_tools()[discoverable_tool_name]
        sig = inspect.signature(method)

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            if param.default is inspect.Parameter.empty and param_name not in args_dict:
                return f"Error: Missing required parameter: {param_name}"

        for arg_name in args_dict:
            if arg_name not in sig.parameters:
                return f"Error: Unexpected parameter: {arg_name}"

        # Call the method directly - it handles checking if tool was given,
        # logging the call, and executing the business logic
        try:
            return method(**args_dict)
        except TypeError as e:
            return f"Error: Invalid arguments for tool '{discoverable_tool_name}': {e}"

    @is_tool(ToolType.READ)
    def list_discoverable_user_tools(self) -> str:
        """List all tools that have been given to you by the agent.

        Use this to see what actions the agent has instructed you to perform.

        Returns:
            A list of tools that have been given to you
        """
        result = query_database_tool("user_discoverable_tools", "{}", db=self.db)

        if "No results found" in result:
            return "No tools have been given to you yet by the agent."

        return f"Tools given to you by the agent:\n{result}"

    @is_tool(ToolType.WRITE)
    def request_human_agent_transfer(self) -> str:
        """Request to be transferred to a human agent for assistance.

        Use this when you want to speak with a real human agent instead of
        the automated system. Each request will be logged and processed.

        Returns:
            Confirmation that your transfer request has been submitted
        """
        # Record this transfer request in the database so the agent can track the count
        today = get_today_str()

        # Query existing requests to get count
        existing_requests = query_database_tool(
            "human_transfer_requests", "{}", db=self.db
        )

        # Count existing requests (simple count based on results)
        if (
            "No records found" in existing_requests
            or "No results found" in existing_requests
        ):
            request_count = 1
        else:
            # Count the number of request entries
            request_count = existing_requests.count("request_id") + 1

        # Create a new request record
        request_id = f"transfer_request_{request_count}"
        record = {
            "request_id": request_id,
            "request_number": request_count,
            "requested_at": today,
            "status": "PENDING",
        }

        add_to_db("human_transfer_requests", request_id, record, db=self.db)

        return (
            f"Transfer request #{request_count} submitted.\n"
            f"The agent will process your request."
        )

    # Reward rates dictionary based on profile.json
    # Maps credit card type -> {category -> reward_percentage}
    # "default" key is used when category doesn't have a special rate
    CREDIT_CARD_REWARDS = {
        # Personal Credit Cards
        "Bronze Rewards Card": {
            "default": 1.0  # 1% on all purchases
        },
        "Silver Rewards Card": {
            "Travel": 4.0,  # 4% on travel
            "Software": 4.0,  # 4% on software
            "default": 1.0,  # 1% on other purchases
        },
        "Gold Rewards Card": {
            "default": 2.5  # 2.5% on all purchases
        },
        "Platinum Rewards Card": {
            "default": 10.0  # 10% on all purchases
        },
        # Business Credit Cards
        "Business Bronze Rewards Card": {
            "default": 1.0  # 1% on all purchases
        },
        "Business Silver Rewards Card": {
            "Travel": 10.0,  # 10% on travel
            "Software": 10.0,  # 10% on software
            "default": 1.0,  # 1% on other purchases
        },
        "Green Rewards Card": {
            "Sustainable": 3.0,  # 3% on sustainable/eco-friendly merchants
            "default": 1.0,  # 1% on other purchases
        },
        "Business Gold Rewards Card": {
            "Operations": 2.5,  # 2.5% on operations spending
            "default": 1.0,  # 1% on other purchases
        },
        "Business Platinum Rewards Card": {
            "Travel": 4.0,  # 4% on travel
            "Software": 4.0,  # 4% on software
            "Media": 4.0,  # 4% on media advertising
            "default": 1.5,  # 1.5% on other purchases
        },
        "Silver Zoom Card": {
            "Transportation": 3.0,  # 3% on transportation/logistics
            "default": 1.0,  # 1% on other purchases
        },
        "Diamond Elite Card": {
            "default": 5.0  # 5% on all purchases (invitation-only)
        },
        # EcoCard uses points (5 pts/$ green, 1 pt/$ other) at $0.01/pt conversion
        # Effective rates: 5% green, 1% other
        "EcoCard": {
            "Green": 5.0,  # 5 pts × $0.01 = 5% equivalent on green purchases
            "default": 1.0,  # 1 pt × $0.01 = 1% equivalent on other purchases
        },
        "Crypto-Cash Back": {
            "default": 2.0  # 2% on all purchases (redeemable to crypto wallet)
        },
    }

    @is_tool(ToolType.WRITE)
    def submit_transaction(
        self,
        user_id: str,
        credit_card_type: str,
        merchant_name: str,
        amount: float,
        category: str,
    ) -> str:
        """Submit a credit card transaction.

        Args:
            user_id: Your user ID
            credit_card_type: Type of credit card used (e.g., "Bronze Rewards Card", "Gold Rewards Card")
            merchant_name: Name of the merchant where the purchase was made
            amount: Transaction amount in USD (e.g., 127.43)
            category: Transaction category (e.g., "Groceries", "Dining", "Travel", "Software", "Entertainment", "Utilities", "Shopping")
        """
        # Validate credit card type
        if credit_card_type not in self.CREDIT_CARD_REWARDS:
            available_cards = list(self.CREDIT_CARD_REWARDS.keys())
            return f"Error: Unknown credit card type '{credit_card_type}'. Available types: {available_cards}"

        # Generate a deterministic transaction ID
        transaction_id = generate_transaction_id(
            user_id, credit_card_type, merchant_name, amount, category
        )

        # Get today's date in MM/DD/YYYY format
        today = get_today_str()

        # Calculate rewards based on credit card type and category
        card_rewards = self.CREDIT_CARD_REWARDS[credit_card_type]
        reward_rate = card_rewards.get(category, card_rewards["default"])

        # Calculate points earned (1 point = 1 cent of cashback)
        # reward_rate is percentage, so 1% means 1 point per dollar
        points_earned = int(amount * reward_rate)

        # Create the transaction record
        record = {
            "transaction_id": transaction_id,
            "user_id": user_id,
            "credit_card_type": credit_card_type,
            "merchant_name": merchant_name,
            "transaction_amount": f"${amount:.2f}",
            "transaction_date": today,
            "category": category,
            "status": "COMPLETED",
            "rewards_earned": f"{points_earned} points",
        }

        # Add to the credit_card_transaction_history table
        success = add_to_db(
            "credit_card_transaction_history", transaction_id, record, db=self.db
        )

        if not success:
            return f"Failed to submit transaction: Record ID '{transaction_id}' may already exist."

        return (
            f"Transaction submitted successfully!\n"
            f"  - Transaction ID: {transaction_id}\n"
            f"  - User ID: {user_id}\n"
            f"  - Card Type: {credit_card_type}\n"
            f"  - Merchant: {merchant_name}\n"
            f"  - Amount: ${amount:.2f}\n"
            f"  - Category: {category}\n"
            f"  - Date: {today}\n"
            f"  - Rewards Earned: {points_earned} points ({reward_rate}% cashback rate)\n"
        )

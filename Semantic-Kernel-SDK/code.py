import asyncio


# Add references
from azure.identity.aio import DefaultAzureCredential
from semantic_kernel.agents import Agent, HandoffOrchestration, OrchestrationHandoffs, AzureAIAgent, AzureAIAgentSettings
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents import (
    AuthorRole,
    ChatMessageContent,
    FunctionCallContent,
    FunctionResultContent,
    StreamingChatMessageContent,
)
from semantic_kernel.functions import kernel_function

ai_agent_settings = AzureAIAgentSettings()


# Define the plugin for handling order-related tasks
class OrderStatusPlugin:
    @kernel_function
    def check_order_status(self, order_id: str) -> str:
        """Check the status of an order."""
        # Simulate checking the order status
        return f"Order {order_id} is shipped and will arrive in 2-3 days."

# Define plugin for handling refunds
class OrderRefundPlugin:
    @kernel_function
    def process_refund(self, order_id: str, reason: str) -> str:
        """Process a refund for an order."""
        # Simulate processing a refund
        print(f"Processing refund for order {order_id} due to: {reason}")
        return f"Refund for order {order_id} has been processed successfully."

# Define plugin for handling order returns
class OrderReturnPlugin:
    @kernel_function
    def process_return(self, order_id: str, reason: str) -> str:
        """Process a return for an order."""
        # Simulate processing a return
        print(f"Processing return for order {order_id} due to: {reason}")
        return f"Return for order {order_id} has been processed successfully."


async def get_agents(project_client, ai_agent_settings) -> tuple[list[Agent], OrchestrationHandoffs]:
    """Return a list of agents that will participate in the Handoff orchestration and the handoff relationships.

    Feel free to add or remove agents and handoff connections.
    """

    # Create the support agent in Azure AI Foundry
    support_agent_definition = await project_client.agents.create_agent(
        model=ai_agent_settings.model_deployment_name,
        name="SupportAgent",
        instructions="Handle customer support requests and triage them to the appropriate agents.",
        description="A customer support agent that triages issues."
    )

    # Create the created support agent as an AzureAIAgent instance
    support_agent = AzureAIAgent(
        client=project_client,
        definition=support_agent_definition
    )


     # Create the Order status agent
    order_status_agent_definition = await project_client.agents.create_agent(
        model=ai_agent_settings.model_deployment_name,
        name="OrderStatusAgent",
         description="A customer support agent that checks order status.",
        instructions="Handle order status requests."
    )
    order_status_agent = AzureAIAgent(
        client=project_client,
        definition=order_status_agent_definition,
        plugins=[OrderStatusPlugin()]
    )

    # Create the Refund agent
    refund_agent_definition = await project_client.agents.create_agent(
        model=ai_agent_settings.model_deployment_name,
        name="RefundAgent",
        description="A customer support agent that handles refunds.",
        instructions="Handle refund requests."
    )
    refund_agent = AzureAIAgent(
        client=project_client,
        definition=refund_agent_definition,
        plugins=[OrderRefundPlugin()]
    )

    # Order return agent as AzureAIAgent
    order_return_agent_definition = await project_client.agents.create_agent(
        model=ai_agent_settings.model_deployment_name,
        name="OrderReturnAgent",
         description="A customer support agent that handles order returns.",
        instructions="Handle order return requests."
    )
    order_return_agent = AzureAIAgent(
        client=project_client,
        definition=order_return_agent_definition,
        plugins=[OrderReturnPlugin()]
    )

    # Define the handoff relationships between agents
    handoffs = (
        OrchestrationHandoffs()
        .add_many(
            source_agent=support_agent.name,
            target_agents={
                refund_agent.name: "Transfer to this agent if the issue is refund related",
                order_status_agent.name: "Transfer to this agent if the issue is order status related",
                order_return_agent.name: "Transfer to this agent if the issue is order return related",
            },
        )
        .add(
            source_agent=refund_agent.name,
            target_agent=support_agent.name,
            description="Transfer to this agent if the issue is not refund related",
        )
        .add(
            source_agent=order_status_agent.name,
            target_agent=support_agent.name,
            description="Transfer to this agent if the issue is not order status related",
        )
        .add(
            source_agent=order_return_agent.name,
            target_agent=support_agent.name,
            description="Transfer to this agent if the issue is not order return related",
        )
    )

    return [support_agent, refund_agent, order_status_agent, order_return_agent], handoffs


# Flag to indicate if a new message is being received
is_new_message = True


def streaming_agent_response_callback(message: StreamingChatMessageContent, is_final: bool) -> None:
    """Observer function to print the messages from the agents.

    Please note that this function is called whenever the agent generates a response,
    including the internal processing messages (such as tool calls) that are not visible
    to other agents in the orchestration.

    In streaming mode, the FunctionCallContent and FunctionResultContent are provided as a
    complete message.

    Args:
        message (StreamingChatMessageContent): The streaming message content from the agent.
        is_final (bool): Indicates if this is the final part of the message.
    """
    global is_new_message
    if is_new_message:
        print(f"{message.name}: ", end="", flush=True)
        is_new_message = False
    print(message.content, end="", flush=True)

    for item in message.items:
        if isinstance(item, FunctionCallContent):
            print(f"Calling '{item.name}' with arguments '{item.arguments}'", end="", flush=True)
        if isinstance(item, FunctionResultContent):
            print(f"Result from '{item.name}' is '{item.result}'", end="", flush=True)

    if is_final:
        print()
        is_new_message = True


def human_response_function() -> ChatMessageContent:
    """Observer function to print the messages from the agents."""
    user_input = input("User: ")
    return ChatMessageContent(role=AuthorRole.USER, content=user_input)


async def main():
    """Main function to run the agents."""
    # 1. Create a handoff orchestration with multiple agents
    
    async with (
        DefaultAzureCredential() as creds,
        AzureAIAgent.create_client(credential=creds, endpoint=ai_agent_settings.endpoint) as project_client,
    ):
    
        agents, handoffs = await get_agents(project_client, ai_agent_settings)
        
        # Create the handoff orchestration with the agents and handoffs
        handoff_orchestration = HandoffOrchestration(
            members=agents,
            handoffs=handoffs,
            streaming_agent_response_callback=streaming_agent_response_callback,
            human_response_function=human_response_function,
        )

        # 2. Create a runtime and start it
        runtime = InProcessRuntime()
        runtime.start()

        # 3. Invoke the orchestration with a task and the runtime
        orchestration_result = await handoff_orchestration.invoke(
            task="Greet the customer who is reaching out for support.",
            runtime=runtime,
        )

        # 4. Wait for the results
        value = await orchestration_result.get()
        print(value)

        # 5. Stop the runtime after the invocation is complete
        await runtime.stop_when_idle()

    """
    Sample output:
    TriageAgent: Hello! Thank you for reaching out for support. How can I assist you today?
    User: I'd like to track the status of my order
    TriageAgent: Calling 'Handoff-transfer_to_OrderStatusAgent' with arguments '{}'
    TriageAgent: Result from 'Handoff-transfer_to_OrderStatusAgent' is 'None'
    OrderStatusAgent: Could you please provide me with your order ID? This will help me check the status of your order.
    User: My order ID is 123
    OrderStatusAgent: Calling 'OrderStatusPlugin-check_order_status' with arguments '{"order_id":"123"}'
    OrderStatusAgent: Result from 'OrderStatusPlugin-check_order_status' is 'Order 123 is shipped and will arrive in
        2-3 days.'
    OrderStatusAgent: Your order with ID 123 has been shipped and is expected to arrive in 2-3 days. If you have any
        more questions, feel free to ask!
    User: I want to return another order of mine
    OrderStatusAgent: Calling 'Handoff-transfer_to_TriageAgent' with arguments '{}'
    OrderStatusAgent: Result from 'Handoff-transfer_to_TriageAgent' is 'None'
    TriageAgent: Calling 'Handoff-transfer_to_OrderReturnAgent' with arguments '{}'
    TriageAgent: Result from 'Handoff-transfer_to_OrderReturnAgent' is 'None'
    OrderReturnAgent: Could you please provide me with the order ID for the order you would like to return, as well
        as the reason for the return?
    User: Order ID 321
    OrderReturnAgent: What is the reason for returning order ID 321?
    User: Broken item
    Processing return for order 321 due to: Broken item
    OrderReturnAgent: Calling 'OrderReturnPlugin-process_return' with arguments '{"order_id":"321","reason":"Broken
        item"}'
    OrderReturnAgent: Result from 'OrderReturnPlugin-process_return' is 'Return for order 321 has been processed
        successfully.'
    OrderReturnAgent: Task is completed with summary: Processed return for order ID 321 due to a broken item.
    Calling 'Handoff-complete_task' with arguments '{"task_summary":"Processed return for order ID 321 due to a
        broken item."}'
    OrderReturnAgent: Result from 'Handoff-complete_task' is 'None'
    """


if __name__ == "__main__":
    asyncio.run(main())
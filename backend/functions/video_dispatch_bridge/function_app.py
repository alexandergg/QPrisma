import logging

import azure.functions as func

from .processor import VideoDispatchBridge
from .settings import BridgeSettings

logger = logging.getLogger(__name__)
app = func.FunctionApp()


@app.service_bus_queue_trigger(
    arg_name="azservicebus",
    queue_name="%ServiceBusQueueName%",
    connection="ServiceBusConnection",
)
async def video_dispatch_bridge(azservicebus: func.ServiceBusMessage) -> None:
    bridge = VideoDispatchBridge(settings=BridgeSettings.from_environment())
    run_id = await bridge.process_message(azservicebus.get_body())
    logger.info("Video dispatch bridge completed with Databricks run_id=%s", run_id)


@app.timer_trigger(
    schedule="%OutboxPollSchedule%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
async def video_outbox_projection(timer: func.TimerRequest) -> None:
    bridge = VideoDispatchBridge(settings=BridgeSettings.from_environment())
    processed_count = await bridge.process_outbox_events()
    if timer.past_due:
        logger.warning("Databricks outbox projection timer is past due")
    logger.info("Databricks outbox projection completed with processed_count=%s", processed_count)

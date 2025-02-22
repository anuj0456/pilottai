import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from pilott import Serve
from pilott.core import BaseAgent, LLMConfig
from pilott.core.task import TaskResult
from pilott.enums.process import ProcessType
from pilott.enums.task_e import TaskPriority

import pytest_asyncio


@pytest.fixture
def llm_config():
    """Fixture for LLM configuration"""
    return LLMConfig(
        model_name="test-model",
        provider="test-provider",
        api_key="test-key"
    )


@pytest_asyncio.fixture
async def mock_agent():
    """Fixture to create a mock agent"""
    agent = Mock(spec=BaseAgent)
    agent.id = "test_agent"
    agent.status = "idle"
    agent.execute_task = AsyncMock(return_value=TaskResult(
        success=True,
        output="Test result",
        execution_time=0.1,
        error=None,
        metadata={}
    ))
    agent.evaluate_task_suitability = AsyncMock(return_value=0.8)
    agent.start = AsyncMock()
    agent.stop = AsyncMock()
    return agent


@pytest_asyncio.fixture
async def serve():
    """Fixture to create a basic Serve instance"""
    serve_instance = Serve(name="TestServe")
    try:
        yield serve_instance
    finally:
        await serve_instance.stop()


class TestServe:
    @pytest.mark.asyncio
    async def test_initialization(self, serve):
        """Test basic initialization of Serve"""
        assert serve.config.name == "TestServe"
        assert serve.config.process_type == ProcessType.SEQUENTIAL
        assert not serve._started
        assert isinstance(serve.agents, dict)
        assert isinstance(serve.tasks, dict)
        assert len(serve.agents) == 0
        assert len(serve.tasks) == 0

    @pytest.mark.asyncio
    async def test_add_agent(self, serve, llm_config):
        """Test adding an agent to Serve"""
        agent = await serve.add_agent(
            role="test_role",
            goal="test goal",
            llm_config=llm_config
        )

        assert "test_role" in serve.agents
        assert isinstance(serve.agents["test_role"], BaseAgent)
        assert agent.config.role == "test_role"
        assert agent.config.goal == "test goal"

    @pytest.mark.asyncio
    async def test_create_task(self, serve):
        """Test task creation"""
        task = await serve.create_task(
            description="Test task",
            priority=TaskPriority.HIGH,
            context={"key": "value"}
        )

        assert task.id in serve.tasks
        assert task.description == "Test task"
        assert task.priority == TaskPriority.HIGH
        assert task.context == {"key": "value"}

    @pytest.mark.asyncio
    async def test_start_stop(self, serve, mock_agent):
        """Test starting and stopping Serve"""
        serve.agents["test"] = mock_agent

        await serve.start()
        assert serve._started
        mock_agent.start.assert_called_once()

        await serve.stop()
        assert not serve._started
        mock_agent.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_sequential(self, serve, mock_agent):
        """Test sequential task execution"""
        serve.agents["test"] = mock_agent
        await serve.start()

        tasks = [
            {"description": "Task 1"},
            {"description": "Task 2"}
        ]

        results = await serve.execute(tasks)

        assert len(results) == 2
        assert all(result.success for result in results)
        assert mock_agent.execute_task.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_parallel(self, serve, mock_agent):
        """Test parallel task execution"""
        serve.agents["test"] = mock_agent
        serve.config.process_type = ProcessType.PARALLEL
        await serve.start()

        tasks = [
            {"description": "Task 1"},
            {"description": "Task 2"}
        ]

        results = await serve.execute(tasks)

        assert len(results) == 2
        assert all(result.success for result in results)
        assert mock_agent.execute_task.call_count == 2

    @pytest.mark.asyncio
    async def test_task_timeout(self, serve, mock_agent):
        """Test task execution timeout"""

        async def timeout_execution(*args, **kwargs):
            await asyncio.sleep(2)
            raise TimeoutError("Task timed out")

        serve.config.task_timeout = 1
        mock_agent.execute_task = AsyncMock(side_effect=timeout_execution)
        serve.agents["test"] = mock_agent
        await serve.start()

        result = await serve.execute([{"description": "Slow task"}])

        assert len(result) == 1
        assert not result[0].success
        assert result[0].error is not None

    @pytest.mark.asyncio
    async def test_error_handling(self, serve, mock_agent):
        """Test error handling during task execution"""
        mock_agent.execute_task = AsyncMock(side_effect=ValueError("Test error"))
        serve.agents["test"] = mock_agent
        await serve.start()

        result = await serve.execute([{"description": "Error task"}])

        assert len(result) == 1
        assert not result[0].success
        assert "Test error" in result[0].error

    @pytest.mark.asyncio
    async def test_get_metrics(self, serve, mock_agent):
        """Test getting system metrics"""
        serve.agents["test"] = mock_agent
        task = await serve.create_task("Test task")

        metrics = serve.get_metrics()

        assert metrics["active_agents"] == 1
        assert metrics["total_tasks"] == 1
        assert metrics["completed_tasks"] == 0
        assert metrics["running_tasks"] == 0
        assert not metrics["is_running"]

    @pytest.mark.asyncio
    async def test_agent_selection(self, serve):
        """Test agent selection for tasks"""
        agent1 = Mock(spec=BaseAgent)
        agent1.evaluate_task_suitability = AsyncMock(return_value=0.5)
        agent1.status = "idle"

        agent2 = Mock(spec=BaseAgent)
        agent2.evaluate_task_suitability = AsyncMock(return_value=0.8)
        agent2.status = "idle"

        serve.agents = {
            "agent1": agent1,
            "agent2": agent2
        }

        task = await serve.create_task("Test task")
        selected_agent = await serve._get_agent_for_task(task)

        assert selected_agent == agent2  # Should select agent with higher suitability

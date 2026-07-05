from __future__ import annotations

import asyncio

import pytest

from openharness.automation.concurrency import WorkflowConcurrencyCoordinator


@pytest.mark.asyncio
async def test_serialize_waits_for_previous_holder() -> None:
    coordinator = WorkflowConcurrencyCoordinator()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with coordinator.slot("incident", "serialize") as lease:
            assert lease.acquired is True
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with coordinator.slot("incident", "serialize") as lease:
            assert lease.acquired is True
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert second_entered.is_set() is False
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set() is True


@pytest.mark.asyncio
async def test_drop_returns_unacquired_lease_when_busy() -> None:
    coordinator = WorkflowConcurrencyCoordinator()
    async with coordinator.slot("incident", "serialize"):
        async with coordinator.slot("incident", "drop") as lease:
            assert lease.acquired is False
            assert "busy" in lease.reason

        # The busy lease must not retain the coordinator guard after yielding.
        async with coordinator.slot("another", "drop") as other:
            assert other.acquired is True


@pytest.mark.asyncio
async def test_cancel_previous_cancels_owner_and_acquires_key() -> None:
    coordinator = WorkflowConcurrencyCoordinator()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def old_run() -> None:
        try:
            async with coordinator.slot("incident", "serialize"):
                entered.set()
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    old_task = asyncio.create_task(old_run())
    await entered.wait()
    async with coordinator.slot("incident", "cancel_previous") as lease:
        assert lease.acquired is True
        await cancelled.wait()
    with pytest.raises(asyncio.CancelledError):
        await old_task


@pytest.mark.asyncio
async def test_empty_key_never_coordinates() -> None:
    coordinator = WorkflowConcurrencyCoordinator()
    async with coordinator.slot("", "drop") as lease:
        assert lease.acquired is True


@pytest.mark.asyncio
async def test_invalid_policy_and_timeout_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        WorkflowConcurrencyCoordinator(cancel_timeout=0)
    coordinator = WorkflowConcurrencyCoordinator()
    with pytest.raises(ValueError, match="unsupported"):
        async with coordinator.slot("key", "unknown"):  # type: ignore[arg-type]
            pass

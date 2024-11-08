# test_binance_bot.py

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

# Import the BinanceBot and BotConfig classes from your bot.py
from bot import BinanceBot, BotConfig

# -----------------------------
# Fixtures for Testing
# -----------------------------

@pytest.fixture
def bot_config():
    """
    Fixture to provide a BotConfig instance for testing.
    """
    return BotConfig(
        symbol="BTCUSDT",
        no_of_decimal_places=1,
        volume=0.01,
        proportion=0.04,
        take_profit_percent=5,
        num_of_grids=10,
        leverage=10,
        testnet=True
    )

@pytest.fixture
def mock_client():
    """
    Fixture to create a mock AsyncClient with AsyncMock methods.
    """
    with patch('bot.AsyncClient') as MockClient:
        mock = MockClient.return_value
        mock.futures_change_leverage = AsyncMock()
        mock.futures_account = AsyncMock()
        mock.futures_create_order = AsyncMock()
        mock.futures_get_open_orders = AsyncMock()
        mock.futures_cancel_order = AsyncMock()
        mock.futures_position_information = AsyncMock()
        mock.futures_mark_price = AsyncMock()
        yield mock

@pytest.fixture
async def bot(bot_config, mock_client):
    """
    Fixture to create a BinanceBot instance with a mocked client.
    """
    bot_instance = BinanceBot(bot_config)
    await bot_instance.initialize_client()
    return bot_instance

# -----------------------------
# Test Cases
# -----------------------------

@pytest.mark.asyncio
async def test_initialize_client(bot, mock_client):
    """
    Test the initialization of the Binance client and setting leverage.
    """
    # Ensure that the client is initialized
    assert bot.client == mock_client

    # Verify that futures_change_leverage was called with correct parameters
    mock_client.futures_change_leverage.assert_awaited_with(
        symbol=bot.config.symbol,
        leverage=bot.config.leverage
    )

@pytest.mark.asyncio
async def test_set_leverage(bot, mock_client):
    """
    Test setting leverage for the bot.
    """
    # The leverage should have been set during initialization
    mock_client.futures_change_leverage.assert_awaited_with(
        symbol=bot.config.symbol,
        leverage=bot.config.leverage
    )

    # Simulate a successful leverage change
    mock_client.futures_change_leverage.return_value = {"leverage": bot.config.leverage}

    # Call set_leverage again to see if it handles correctly
    await bot.set_leverage()

    mock_client.futures_change_leverage.assert_awaited_with(
        symbol=bot.config.symbol,
        leverage=bot.config.leverage
    )

@pytest.mark.asyncio
async def test_get_balance(bot, mock_client):
    """
    Test retrieving the account balance.
    """
    # Mock the futures_account response
    mock_balance = {
        "assets": [
            {
                "asset": "USDT",
                "walletBalance": "1000.0",
                "unrealizedProfit": "0.0",
                "marginBalance": "1000.0",
                "maintMargin": "0.0",
                "positionInitialMargin": "0.0",
                "openOrderInitialMargin": "0.0",
                "isolatedWallet": "0.0",
                "maxWithdrawAmount": "1000.0"
            }
        ]
    }
    mock_client.futures_account.return_value = mock_balance

    balance_df = await bot.get_balance()

    # Verify that the DataFrame is correctly created
    expected_df = pd.DataFrame(mock_balance['assets'])
    pd.testing.assert_frame_equal(balance_df, expected_df)

    # Ensure that futures_account was called with no arguments
    mock_client.futures_account.assert_awaited_once()

@pytest.mark.asyncio
async def test_place_limit_order(bot, mock_client):
    """
    Test placing a limit order.
    """
    # Mock the futures_create_order response
    mock_order_response = {
        "symbol": bot.config.symbol,
        "orderId": 123456,
        "orderListId": -1,
        "clientOrderId": "test_order",
        "transactTime": 1609459200000,
        "price": "50000.0",
        "origQty": "0.01",
        "executedQty": "0.0",
        "status": "NEW",
        "timeInForce": "GTC",
        "type": "LIMIT",
        "side": "BUY",
        "fills": []
    }
    mock_client.futures_create_order.return_value = mock_order_response

    # Call place_limit_order
    order = await bot.place_limit_order("BUY", 0.01, 50000.0)

    # Verify the response
    assert order == mock_order_response

    # Ensure that futures_create_order was called with correct parameters
    mock_client.futures_create_order.assert_awaited_with(
        symbol=bot.config.symbol,
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity=0.01,
        price="50000.0"
    )

@pytest.mark.asyncio
async def test_cancel_orders(bot, mock_client):
    """
    Test cancelling orders, both all orders and filtered by side.
    """
    # Mock open orders
    mock_open_orders = [
        {"orderId": 1, "side": "BUY"},
        {"orderId": 2, "side": "SELL"},
        {"orderId": 3, "side": "BUY"},
    ]
    mock_client.futures_get_open_orders.return_value = mock_open_orders

    # Call cancel_orders without side (cancel all)
    await bot.cancel_orders()

    # Verify that futures_get_open_orders was called
    mock_client.futures_get_open_orders.assert_awaited_with(symbol=bot.config.symbol)

    # Verify that futures_cancel_order was called for each order
    expected_calls = [
        patch.call(symbol=bot.config.symbol, orderId=1),
        patch.call(symbol=bot.config.symbol, orderId=2),
        patch.call(symbol=bot.config.symbol, orderId=3),
    ]
    actual_calls = [call.args for call in mock_client.futures_cancel_order.await_args_list]
    expected_order_ids = [1, 2, 3]
    actual_order_ids = [call[1]['orderId'] for call in mock_client.futures_cancel_order.await_args_list]
    assert actual_order_ids == expected_order_ids

    # Reset mock
    mock_client.futures_cancel_order.reset_mock()

    # Call cancel_orders with side='BUY'
    await bot.cancel_orders(side='BUY')

    # Verify that only BUY orders were cancelled
    mock_client.futures_get_open_orders.assert_awaited_with(symbol=bot.config.symbol)
    expected_buy_order_ids = [1, 3]
    actual_buy_order_ids = [call[1]['orderId'] for call in mock_client.futures_cancel_order.await_args_list]
    assert actual_buy_order_ids == expected_buy_order_ids

@pytest.mark.asyncio
async def test_get_position_direction_long(bot, mock_client):
    """
    Test determining position direction when the position is LONG.
    """
    # Mock position information with positive positionAmt
    mock_positions = [
        {
            "symbol": bot.config.symbol,
            "positionAmt": "0.01",
            "entryPrice": "50000.0",
            "leverage": "10",
            # ... other fields
        }
    ]
    mock_client.futures_position_information.return_value = mock_positions

    direction = await bot.get_position_direction()

    assert direction == "LONG"
    mock_client.futures_position_information.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_get_position_direction_short(bot, mock_client):
    """
    Test determining position direction when the position is SHORT.
    """
    # Mock position information with negative positionAmt
    mock_positions = [
        {
            "symbol": bot.config.symbol,
            "positionAmt": "-0.01",
            "entryPrice": "50000.0",
            "leverage": "10",
            # ... other fields
        }
    ]
    mock_client.futures_position_information.return_value = mock_positions

    direction = await bot.get_position_direction()

    assert direction == "SHORT"
    mock_client.futures_position_information.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_get_position_direction_flat(bot, mock_client):
    """
    Test determining position direction when there is no open position.
    """
    # Mock position information with zero positionAmt
    mock_positions = [
        {
            "symbol": bot.config.symbol,
            "positionAmt": "0.000",
            "entryPrice": "50000.0",
            "leverage": "10",
            # ... other fields
        }
    ]
    mock_client.futures_position_information.return_value = mock_positions

    direction = await bot.get_position_direction()

    assert direction == "FLAT"
    mock_client.futures_position_information.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_get_mark_price(bot, mock_client):
    """
    Test retrieving the current mark price.
    """
    # Mock mark price response
    mock_mark_price = {"symbol": bot.config.symbol, "markPrice": "50000.0"}
    mock_client.futures_mark_price.return_value = mock_mark_price

    price = await bot.get_mark_price()

    assert price == 50000.0
    mock_client.futures_mark_price.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_calculate_take_profit_level(bot, mock_client):
    """
    Test calculating the take-profit level based on open positions.
    """
    # Mock position information
    mock_positions = [
        {
            "symbol": bot.config.symbol,
            "positionAmt": "0.01",
            "entryPrice": "50000.0",
            "leverage": "10",
            # ... other fields
        }
    ]
    mock_client.futures_position_information.return_value = mock_positions

    tp_price, tp_amount = await bot.calculate_take_profit_level()

    # Calculate expected TP price
    # margin = (50000 * 0.01) / 10 = 50
    # profit = 50 * 0.05 = 2.5
    # tp_price = 50000 + (2.5 / 0.01) = 50000 + 250 = 50250.0
    assert tp_price == 50250.0
    assert tp_amount == 0.01
    mock_client.futures_position_information.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_calculate_take_profit_level_no_position(bot, mock_client):
    """
    Test calculating the take-profit level when there are no open positions.
    """
    # Mock position information with no open positions
    mock_positions = [
        {
            "symbol": bot.config.symbol,
            "positionAmt": "0.000",
            "entryPrice": "50000.0",
            "leverage": "10",
            # ... other fields
        }
    ]
    mock_client.futures_position_information.return_value = mock_positions

    tp_price, tp_amount = await bot.calculate_take_profit_level()

    assert tp_price is None
    assert tp_amount is None
    mock_client.futures_position_information.assert_awaited_with(symbol=bot.config.symbol)

@pytest.mark.asyncio
async def test_place_take_profit_order_long(bot, mock_client):
    """
    Test placing a take-profit order for a LONG position.
    """
    # Mock the place_limit_order method
    with patch.object(bot, 'place_limit_order', new=AsyncMock()) as mock_place_order:
        # Call place_take_profit_order
        await bot.place_take_profit_order(price=50250.0, amount=0.01, direction="LONG")

        # Verify that place_limit_order was called with SELL side
        mock_place_order.assert_awaited_with("SELL", 0.01, 50250.0)

@pytest.mark.asyncio
async def test_place_take_profit_order_short(bot, mock_client):
    """
    Test placing a take-profit order for a SHORT position.
    """
    # Mock the place_limit_order method
    with patch.object(bot, 'place_limit_order', new=AsyncMock()) as mock_place_order:
        # Call place_take_profit_order
        await bot.place_take_profit_order(price=49750.0, amount=0.01, direction="SHORT")

        # Verify that place_limit_order was called with BUY side
        mock_place_order.assert_awaited_with("BUY", 0.01, 49750.0)

@pytest.mark.asyncio
async def test_draw_grid(bot, mock_client):
    """
    Test drawing grid orders around the current market price.
    """
    # Mock the get_mark_price method
    with patch.object(bot, 'get_mark_price', new=AsyncMock(return_value=50000.0)):
        # Mock the place_limit_order method
        with patch.object(bot, 'place_limit_order', new=AsyncMock()) as mock_place_order:
            await bot.draw_grid()

            # Verify that place_limit_order was called correct number of times
            assert mock_place_order.await_count == bot.config.num_of_grids * 2  # Buy and Sell for each grid

            # Optionally, verify specific calls (e.g., first and last grid)
            first_sell_price = round(50000.0 * (1 + bot.config.proportion * 1 / 100), bot.config.no_of_decimal_places)
            first_buy_price = round(50000.0 * (1 - bot.config.proportion * 1 / 100), bot.config.no_of_decimal_places)
            mock_place_order.assert_any_await("SELL", bot.config.volume, first_sell_price)
            mock_place_order.assert_any_await("BUY", bot.config.volume, first_buy_price)

@pytest.mark.asyncio
async def test_monitor_position_flat(bot, mock_client):
    """
    Test the monitor_position method when the position is FLAT.
    """
    # Mock get_position_direction to return FLAT
    with patch.object(bot, 'get_position_direction', new=AsyncMock(return_value="FLAT")):
        # Mock draw_grid
        with patch.object(bot, 'draw_grid', new=AsyncMock()) as mock_draw_grid:
            # Run monitor_position for a limited time to test behavior
            async def stop_after_delay():
                await asyncio.sleep(0.1)
                raise asyncio.CancelledError

            with patch('asyncio.sleep', new=AsyncMock()):
                monitor_task = asyncio.create_task(bot.monitor_position())
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

            # Verify that draw_grid was called
            mock_draw_grid.assert_awaited_once()

@pytest.mark.asyncio
async def test_monitor_position_long(bot, mock_client):
    """
    Test the monitor_position method when the position is LONG.
    """
    # Mock get_position_direction to first return LONG, then FLAT
    with patch.object(bot, 'get_position_direction', new=AsyncMock(side_effect=["LONG", "FLAT"])):
        # Mock calculate_take_profit_level
        with patch.object(bot, 'calculate_take_profit_level', new=AsyncMock(return_value=(50250.0, 0.01))):
            # Mock place_take_profit_order
            with patch.object(bot, 'place_take_profit_order', new=AsyncMock()) as mock_place_tp:
                # Mock cancel_orders
                with patch.object(bot, 'cancel_orders', new=AsyncMock()) as mock_cancel_orders:
                    # Mock asyncio.sleep to avoid actual delays
                    with patch('asyncio.sleep', new=AsyncMock()):
                        # Run monitor_position for a limited time to test behavior
                        async def stop_after_delay():
                            await asyncio.sleep(0.1)
                            raise asyncio.CancelledError

                        monitor_task = asyncio.create_task(bot.monitor_position())
                        monitor_task.cancel()
                        try:
                            await monitor_task
                        except asyncio.CancelledError:
                            pass

                        # Verify that cancel_orders was called with opposing side
                        mock_cancel_orders.assert_awaited_with(side="SELL")

                        # Verify that calculate_take_profit_level was called
                        mock_place_tp.assert_awaited_with(price=50250.0, amount=0.01, direction="LONG")

# -----------------------------
# Additional Tests (Optional)
# -----------------------------

# You can add more tests to cover edge cases, error handling, and other scenarios.
# For example:

@pytest.mark.asyncio
async def test_place_limit_order_exception(bot, mock_client):
    """
    Test placing a limit order when an exception occurs.
    """
    # Configure the mock to raise an exception
    mock_client.futures_create_order.side_effect = Exception("API Error")

    # Call place_limit_order and ensure it returns None
    order = await bot.place_limit_order("BUY", 0.01, 50000.0)
    assert order is None

@pytest.mark.asyncio
async def test_get_mark_price_exception(bot, mock_client):
    """
    Test getting mark price when an exception occurs.
    """
    # Configure the mock to raise an exception
    mock_client.futures_mark_price.side_effect = Exception("API Error")

    # Call get_mark_price and ensure it returns None
    price = await bot.get_mark_price()
    assert price is None

# Add more tests as needed to cover all functionalities and edge cases.

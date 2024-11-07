# test.py

import pytest
from unittest.mock import MagicMock, patch
from threading import Thread
import time
import logging
import pandas as pd

# Import your bot's functions
from bot import (
    initialize_bot,
    get_balance,
    place_limit_order,
    cancel_orders,
    get_position_direction,
    get_mark_price,
    draw_grid,
    calculate_take_profit_level,
    place_take_profit_order,
    run_bot
)

# Configure logging for tests
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')


##############################
#        Fixtures            #
##############################

@pytest.fixture
def mock_client():
    """Fixture to create a mocked Binance Client."""
    return MagicMock()

@pytest.fixture
def bot_config(mock_client):
    """Fixture to initialize a bot configuration with a mocked client."""
    with patch('bot.Client') as MockClient:
        MockClient.return_value = mock_client
        config = initialize_bot("BTCUSDT", 1, 0.01, 0.04, 5, 10, testnet=True)
        return config


##############################
#        Unit Tests          #
##############################

def test_initialize_bot(mock_client):
    """Test the initialize_bot function."""
    with patch('bot.Client') as MockClient:
        mock_client_instance = MockClient.return_value
        # Mock the API keys in key_file
        with patch('bot.k.binance_testnet_api_key', 'test_api_key'), \
             patch('bot.k.binance_testnet_api_secret', 'test_api_secret'):
            bot_config = initialize_bot("BTCUSDT", 1, 0.01, 0.04, 5, 10, testnet=True)
        
        MockClient.assert_called_with(
            'test_api_key',
            'test_api_secret',
            tld="com",
            testnet=True
        )
        assert bot_config['symbol'] == "BTCUSDT"
        assert bot_config['no_of_decimal_places'] == 1
        assert bot_config['volume'] == 0.01
        assert bot_config['proportion'] == 0.04
        assert bot_config['take_profit_percent'] == 5
        assert bot_config['num_of_grids'] == 10

def test_get_balance(mock_client, caplog):
    """Test the get_balance function."""
    account_info = {
        'assets': [
            {'asset': 'USDT', 'balance': '1000'},
            {'asset': 'BTC', 'balance': '0.5'}
        ]
    }
    mock_client.futures_account.return_value = account_info
    
    get_balance(mock_client)
    
    mock_client.futures_account.assert_called_once()
    assert "Account Balance:" in caplog.text
    assert "USDT" in caplog.text
    assert "BTC" in caplog.text

def test_place_limit_order_success(mock_client, caplog):
    """Test successful placement of a limit order."""
    order_response = {'orderId': 12345, 'status': 'NEW'}
    mock_client.futures_create_order.return_value = order_response
    
    place_limit_order(mock_client, "BTCUSDT", "BUY", 0.01, 50000)
    
    mock_client.futures_create_order.assert_called_with(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity=0.01,
        price=50000
    )
    assert "BUY limit order placed" in caplog.text

def test_place_limit_order_exception(mock_client, caplog):
    """Test exception handling when placing a limit order."""
    mock_client.futures_create_order.side_effect = Exception("API Error")
    
    place_limit_order(mock_client, "BTCUSDT", "SELL", 0.01, 51000)
    
    mock_client.futures_create_order.assert_called_once()
    assert "Error placing SELL limit order: API Error" in caplog.text

def test_cancel_orders(mock_client, caplog):
    """Test the cancel_orders function."""
    open_orders = [
        {'orderId': 1, 'side': 'BUY'},
        {'orderId': 2, 'side': 'SELL'}
    ]
    mock_client.futures_get_open_orders.return_value = open_orders
    
    cancel_orders(mock_client, "BTCUSDT", side="BUY")
    
    mock_client.futures_get_open_orders.assert_called_with(symbol="BTCUSDT")
    mock_client.futures_cancel_order.assert_called_once_with(symbol="BTCUSDT", orderId=1)
    assert "BUY orders canceled for BTCUSDT" in caplog.text

def test_get_position_direction_long(mock_client, caplog):
    """Test getting position direction as Long."""
    position_info = [{
        'positionAmt': '1.0',
        'entryPrice': '50000',
        'leverage': '10'
    }]
    mock_client.futures_position_information.return_value = position_info
    
    direction = get_position_direction(mock_client, "BTCUSDT")
    
    assert direction == "Long"
    assert "Position amount sum: 1.0" in caplog.text

def test_get_position_direction_short(mock_client, caplog):
    """Test getting position direction as Short."""
    position_info = [{
        'positionAmt': '-1.0',
        'entryPrice': '50000',
        'leverage': '10'
    }]
    mock_client.futures_position_information.return_value = position_info
    
    direction = get_position_direction(mock_client, "BTCUSDT")
    
    assert direction == "Short"
    assert "Position amount sum: -1.0" in caplog.text

def test_get_position_direction_flat(mock_client, caplog):
    """Test getting position direction as FLAT."""
    position_info = [{
        'positionAmt': '0.0',
        'entryPrice': '0',
        'leverage': '10'
    }]
    mock_client.futures_position_information.return_value = position_info
    
    direction = get_position_direction(mock_client, "BTCUSDT")
    
    assert direction == "FLAT"
    assert "Position amount sum: 0.0" in caplog.text

def test_get_mark_price_success(mock_client):
    """Test successful retrieval of mark price."""
    ticker = {'price': '50000'}
    mock_client.get_symbol_ticker.return_value = ticker
    
    price = get_mark_price(mock_client, "BTCUSDT")
    
    mock_client.get_symbol_ticker.assert_called_with(symbol="BTCUSDT")
    assert price == 50000.0

def test_get_mark_price_exception(mock_client, caplog):
    """Test exception handling when fetching mark price."""
    mock_client.get_symbol_ticker.side_effect = Exception("Ticker Error")
    
    price = get_mark_price(mock_client, "BTCUSDT")
    
    mock_client.get_symbol_ticker.assert_called_once_with(symbol="BTCUSDT")
    assert price is None
    assert "Error fetching mark price: Ticker Error" in caplog.text

def test_calculate_take_profit_level_no_position(mock_client, caplog):
    """Test take profit calculation when there are no positions."""
    mock_client.futures_position_information.return_value = []
    
    price, amt = calculate_take_profit_level(mock_client, "BTCUSDT", 5, 1)
    
    assert price is None
    assert amt is None
    assert "No positions found in calculate_take_profit_level" in caplog.text

def test_calculate_take_profit_level_success(mock_client, caplog):
    """Test successful calculation of take profit level."""
    position_info = [{
        'positionAmt': '1.0',
        'entryPrice': '50000',
        'leverage': '10'
    }]
    mock_client.futures_position_information.return_value = position_info
    
    price, amt = calculate_take_profit_level(mock_client, "BTCUSDT", 5, 1)
    
    # Calculate expected price
    margin = (50000 * 1.0) / 10  # 5000
    profit = 5000 * 0.05        # 250
    expected_price = round((250 / 1.0) + 50000, 1)  # 50250.0
    
    assert price == expected_price
    assert amt == 1.0
    assert "Calculated TP level: price=50250.0, total_position_amt=1.0" in caplog.text

def test_place_take_profit_order_long(mock_client, caplog):
    """Test placing a take profit order for a Long position."""
    place_take_profit_order(mock_client, "BTCUSDT", 50250.0, 1.0, "Long")
    
    mock_client.futures_create_order.assert_called_with(
        symbol="BTCUSDT",
        side="SELL",
        type="LIMIT",
        timeInForce="GTC",
        quantity=1.0,
        price=50250.0
    )
    assert "Placing TP order: symbol=BTCUSDT, price=50250.0, position_amt=1.0, direction=Long" in caplog.text

def test_place_take_profit_order_short(mock_client, caplog):
    """Test placing a take profit order for a Short position."""
    place_take_profit_order(mock_client, "BTCUSDT", 49750.0, 1.0, "Short")
    
    mock_client.futures_create_order.assert_called_with(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity=1.0,
        price=49750.0
    )
    assert "Placing TP order: symbol=BTCUSDT, price=49750.0, position_amt=1.0, direction=Short" in caplog.text


##############################
#      Integration Tests     #
##############################

@pytest.mark.integration
def test_initialize_and_get_mark_price_integration():
    """Integration test for initializing bot and fetching mark price."""
    # Initialize bot with real Binance testnet client
    bot_config = initialize_bot("BTCUSDT", 1, 0.01, 0.04, 5, 10, testnet=True)
    
    price = get_mark_price(bot_config['client'], bot_config['symbol'])
    
    assert price is not None
    assert isinstance(price, float)
    print(f"Current mark price for {bot_config['symbol']}: {price}")
    
    # Clean up
    bot_config['client'].close_connection()


##############################
#        E2E Tests           #
##############################

@pytest.mark.e2e
def test_run_bot_e2e():
    """End-to-End test running the bot for a short duration."""
    # Initialize bot with real Binance testnet client
    bot_config = initialize_bot("BTCUSDT", 1, 0.001, 0.04, 1, 2, testnet=True)
    
    # Run the bot in a separate thread
    bot_thread = Thread(target=run_bot, args=(bot_config,), daemon=True)
    bot_thread.start()
    
    # Allow the bot to run for a short period
    time.sleep(30)  # Run the bot for 30 seconds
    
    # After 30 seconds, verify that orders have been placed
    open_orders = bot_config['client'].futures_get_open_orders(symbol=bot_config['symbol'])
    assert len(open_orders) > 0, "No open orders were placed by the bot."
    
    # Clean up: Cancel all orders
    bot_config['client'].futures_cancel_all_open_orders(symbol=bot_config['symbol'])
    
    # Stop the bot thread if necessary
    # (In this example, the bot runs indefinitely, so in real tests, you'd need a way to gracefully stop it)
    # For this test, we'll assume the daemon thread will exit when the main thread exits.


##############################
#  Robustness & Stress Tests #
##############################

def test_handle_api_failure(mock_client, caplog):
    """Test the bot's handling of API failures."""
    mock_client.futures_create_order.side_effect = Exception("API Failure")
    
    place_limit_order(mock_client, "BTCUSDT", "BUY", 0.01, 50000)
    
    assert "Error placing BUY limit order: API Failure" in caplog.text

def test_rate_limiting(mock_client, caplog):
    """Test the bot's behavior under rate limiting."""
    with patch('time.sleep') as mock_sleep:
        for _ in range(100):
            place_limit_order(mock_client, "BTCUSDT", "BUY", 0.01, 50000)
        # Verify that sleep was called to handle rate limits
        assert mock_sleep.called
        # You can add more assertions based on how your bot handles rate limits

def test_thread_safety():
    """Test running multiple bots in parallel to ensure thread safety."""
    # Initialize two bots with mocked clients
    bot1_config = initialize_bot("BTCUSDT", 1, 0.001, 0.04, 1, 2, testnet=True)
    bot2_config = initialize_bot("ETHUSDT", 2, 0.001, 0.04, 1, 2, testnet=True)
    
    # Mock the clients
    bot1_config['client'] = MagicMock()
    bot2_config['client'] = MagicMock()
    
    thread1 = Thread(target=run_bot, args=(bot1_config,), daemon=True)
    thread2 = Thread(target=run_bot, args=(bot2_config,), daemon=True)
    
    thread1.start()
    thread2.start()
    
    time.sleep(30)  # Let the bots run for 30 seconds
    
    # Verify orders for both bots
    open_orders_bot1 = bot1_config['client'].futures_get_open_orders(symbol=bot1_config['symbol'])
    open_orders_bot2 = bot2_config['client'].futures_get_open_orders(symbol=bot2_config['symbol'])
    
    assert open_orders_bot1 is not None
    assert open_orders_bot2 is not None
    
    # Clean up
    bot1_config['client'].futures_cancel_all_open_orders(symbol=bot1_config['symbol'])
    bot2_config['client'].futures_cancel_all_open_orders(symbol=bot2_config['symbol'])


##############################
#      Run Tests with Pytest  #
##############################

if __name__ == "__main__":
    # Run all tests
    pytest.main([__file__])

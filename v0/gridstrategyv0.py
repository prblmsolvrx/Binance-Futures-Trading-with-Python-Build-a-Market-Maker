import logging
import time
import pandas as pd
from threading import Thread
from binance.client import Client

import key_file as k  # Ensure this file contains your Binance API keys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

def initialize_bot(symbol, no_of_decimal_places, volume, proportion, take_profit_percent, num_of_grids, leverage=1, testnet=False):
    """Initialize and return a bot configuration."""
    # Create a Binance client instance
    client = Client(
        k.binance_testnet_api_key,
        k.binance_testnet_api_secret,
        tld="com",
        testnet=testnet
    )
    
    # Set leverage for the symbol
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        logging.info(f"Leverage set to {leverage}x for {symbol}")
    except Exception as e:
        logging.error(f"Error setting leverage for {symbol}: {e}")
    
    # Optionally, verify leverage
    try:
        position_info = client.futures_position_information(symbol=symbol)
        df = pd.DataFrame(position_info)
        current_leverage = df["leverage"].iloc[0] if 'leverage' in df.columns else "Not Set"
        logging.info(f"Current leverage for {symbol}: {current_leverage}x")
    except Exception as e:
        logging.error(f"Error retrieving leverage for {symbol}: {e}")
    
    bot_config = {
        'client': client,
        'symbol': symbol,
        'no_of_decimal_places': no_of_decimal_places,
        'volume': volume,
        'proportion': proportion,
        'take_profit_percent': take_profit_percent,
        'num_of_grids': num_of_grids
    }
    return bot_config

def get_balance(client):
    """Retrieve and log account balance information."""
    try:
        account_info = client.futures_account()
        df = pd.DataFrame(account_info['assets'])
        logging.info(f"Account Balance:\n{df}")
    except Exception as e:
        logging.error(f"Error retrieving account balance: {e}")

def place_limit_order(client, symbol, side, volume, price):
    """Place a limit order and log the result."""
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=Client.FUTURE_ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            quantity=volume,
            price=price,
        )
        logging.info(f"{side} limit order placed: {order}")
    except Exception as e:
        logging.error(f"Error placing {side} limit order: {e}")

def cancel_orders(client, symbol, side=None):
    """Cancel open orders for a symbol, optionally filtering by side."""
    try:
        open_orders = client.futures_get_open_orders(symbol=symbol)
        df = pd.DataFrame(open_orders)
        if side:
            df = df[df['side'] == side]
        for _, order in df.iterrows():
            client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
        logging.info(f"All {'{} '.format(side) if side else ''}orders canceled for {symbol}")
    except Exception as e:
        logging.error(f"Error canceling orders: {e}")

def get_position_direction(client, symbol):
    """Determine the current position direction (Long, Short, or FLAT)."""
    try:
        position_info = client.futures_position_information(symbol=symbol)
        df = pd.DataFrame(position_info)
        if 'positionAmt' in df.columns:
            df['positionAmt'] = pd.to_numeric(df['positionAmt'], errors='coerce')
            position_amt_sum = df['positionAmt'].sum()
            logging.info(f"Position amount sum: {position_amt_sum}")
            if position_amt_sum > 0:
                return "Long"
            elif position_amt_sum < 0:
                return "Short"
        else:
            logging.warning("'positionAmt' column is missing in the data.")
        return "FLAT"
    except Exception as e:
        logging.error(f"Error determining position direction: {e}")
        return "FLAT"

def get_mark_price(client, symbol):
    """Retrieve the current mark price for a symbol."""
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logging.error(f"Error fetching mark price: {e}")
        return None

def draw_grid(bot_config):
    """Draw grid of limit orders above and below the current price."""
    client = bot_config['client']
    symbol = bot_config['symbol']
    no_of_decimal_places = bot_config['no_of_decimal_places']
    volume = bot_config['volume']
    proportion = bot_config['proportion']
    num_of_grids = bot_config['num_of_grids']
    
    current_price = get_mark_price(client, symbol)
    if current_price is None:
        return

    # Place sell limit orders
    pct_change = 1
    adj_sell = 1.2
    for _ in range(num_of_grids):
        sell_price = round(
            ((pct_change / 100) * current_price * adj_sell * proportion) + current_price,
            no_of_decimal_places
        )
        place_limit_order(client, symbol, Client.SIDE_SELL, volume, sell_price)
        pct_change += 1
        adj_sell += 0.2

    # Place buy limit orders
    pct_change = -1
    adj_buy = 1.2
    for _ in range(num_of_grids):
        buy_price = round(
            ((pct_change / 100) * current_price * adj_buy * proportion) + current_price,
            no_of_decimal_places
        )
        place_limit_order(client, symbol, Client.SIDE_BUY, volume, buy_price)
        pct_change -= 1
        adj_buy -= 0.2

def calculate_take_profit_level(client, symbol, take_profit_percent, no_of_decimal_places):
    """Calculate the take-profit price level based on current positions."""
    try:
        position_info = client.futures_position_information(symbol=symbol)
        logging.debug(f"Position Info for {symbol}: {position_info}")  # Debug log
        df = pd.DataFrame(position_info)
        df = df[df["positionAmt"] != "0.000"]
        if df.empty:
            logging.info("No positions found in calculate_take_profit_level")
            return None, None

        entry_price = float(df["entryPrice"].iloc[0])
        position_amt = float(df["positionAmt"].iloc[0])

        # Safely retrieve leverage
        leverage = df["leverage"].iloc[0] if 'leverage' in df.columns else None
        if leverage is None or leverage == "":
            logging.warning(f"Leverage not set for {symbol}. Setting default leverage to 1.")
            leverage = 1  # Default leverage
        else:
            leverage = float(leverage)

        margin = (entry_price * abs(position_amt)) / leverage
        profit = margin * take_profit_percent * 0.01
        price = round((profit / position_amt) + entry_price, no_of_decimal_places)
        total_position_amt = abs(position_amt)

        logging.info(f"Calculated TP level: price={price}, total_position_amt={total_position_amt}")
        return price, total_position_amt
    except Exception as e:
        logging.error(f"Exception in calculate_take_profit_level: {e}")
        return None, None

def place_take_profit_order(client, symbol, price, position_amt, direction):
    """Place a take-profit order based on the current position."""
    side = Client.SIDE_SELL if direction == "Long" else Client.SIDE_BUY
    logging.info(
        f"Placing TP order: symbol={symbol}, price={price}, position_amt={position_amt}, direction={direction}"
    )
    place_limit_order(client, symbol, side, position_amt, price)

def run_bot(bot_config):
    """Main function to run the trading bot."""
    client = bot_config['client']
    symbol = bot_config['symbol']
    no_of_decimal_places = bot_config['no_of_decimal_places']
    volume = bot_config['volume']
    proportion = bot_config['proportion']
    take_profit_percent = bot_config['take_profit_percent']
    num_of_grids = bot_config['num_of_grids']

    while True:
        try:
            # Check for open orders
            open_orders = client.futures_get_open_orders(symbol=symbol)
            if not open_orders:
                logging.info(f"No open orders found for {symbol}. Drawing grid...")
                draw_grid(bot_config)

            # Check for existing positions
            direction = get_position_direction(client, symbol)

            if direction != "FLAT":
                # Close opposing orders
                opposing_side = 'SELL' if direction == "Long" else 'BUY'
                logging.info(f"Position is {direction}. Closing {opposing_side.lower()} orders for {symbol}...")
                cancel_orders(client, symbol, side=opposing_side)

                # Place take-profit order
                tp_price, tp_amount = calculate_take_profit_level(client, symbol, take_profit_percent, no_of_decimal_places)
                if tp_price and tp_amount:
                    place_take_profit_order(client, symbol, tp_price, tp_amount, direction)

                # Monitor the position and adjust TP orders if needed
                while True:
                    try:
                        new_tp_price, new_tp_amount = calculate_take_profit_level(client, symbol, take_profit_percent, no_of_decimal_places)
                        if new_tp_price != tp_price or new_tp_amount != tp_amount:
                            logging.info("TP level changed. Updating orders...")
                            cancel_orders(client, symbol, side='SELL' if direction == "Long" else 'BUY')
                            place_take_profit_order(client, symbol, new_tp_price, new_tp_amount, direction)
                            tp_price, tp_amount = new_tp_price, new_tp_amount
                    except Exception as e:
                        logging.error(f"Exception in monitoring loop: {e}")

                    # Check if position is closed
                    current_position = get_position_direction(client, symbol)
                    if current_position == "FLAT":
                        logging.info(f"Position closed for {symbol}. Closing all orders...")
                        cancel_orders(client, symbol)
                        break

                    time.sleep(1)
            else:
                logging.info(f"Waiting for a position to open for {symbol}...")

            time.sleep(5)
        except Exception as e:
            logging.error(f"Exception in run_bot loop: {e}")
            time.sleep(5)  # Wait before retrying

# Start the bots in separate threads
if __name__ == "__main__":
    # Initialize bots with specified parameters and leverage
    bot1 = initialize_bot("BTCUSDT", 1, 0.01, 0.04, 5, 10, leverage=10, testnet=True)
    bot2 = initialize_bot("ETHUSDT", 2, 0.01, 0.04, 5, 10, leverage=10, testnet=True)

    def run_bot1():
        """Thread function to run bot1."""
        try:
            logging.info("Starting bot1 for BTCUSDT...")
            run_bot(bot1)
        except Exception as e:
            logging.error(f"Error running bot1: {e}")

    def run_bot2():
        """Thread function to run bot2."""
        try:
            logging.info("Starting bot2 for ETHUSDT...")
            run_bot(bot2)
        except Exception as e:
            logging.error(f"Error running bot2: {e}")

    # Start each bot in its own thread for parallel execution
    logging.info("Initializing and starting bot threads...")
    t1 = Thread(target=run_bot1)
    t2 = Thread(target=run_bot2)

    t1.start()
    t2.start()

    # Join threads to ensure the main program waits for both bots to complete
    t1.join()
    t2.join()

    logging.info("Both bot threads have completed.")

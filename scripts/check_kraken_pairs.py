
import ccxt
import sys

def check_pairs():
    try:
        exchange = ccxt.kraken()
        markets = exchange.load_markets()
        
        print("Searching for USD/JPY pairs...")
        found = False
        for symbol in markets:
            if "JPY" in symbol and "USD" in symbol:
                print(f"Found: {symbol}")
                ticker = exchange.fetch_ticker(symbol)
                print(f"  Price: {ticker['last']}")
                found = True
        
        if not found:
            print("No USD/JPY pair found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pairs()

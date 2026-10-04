"""Apply numbered remote-store migrations before starting the single relay worker."""
import argparse
from .config import ServerConfig,load
from .db import open_database,migrate


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    config=load(parser.parse_args().config,ServerConfig)
    engine=open_database(config.database_secret.read() if config.database_secret else config.database_url)
    try:
        migrate(engine)
        print('Remote schema is at version 1')
    finally:
        engine.dispose()


if __name__=='__main__':
    main()

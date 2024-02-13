import argparse
from dotenv import load_dotenv
import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime, date
import pandas as pd
from utils.power_nasa_utils import get_data as get_meteo_data
from utils.fire_index_utils import get_data_with_fire_indexes
from utils.maryland_fuoco_utils import get_daily_burned_area_data
from utils.gfed_utils import get_gfed_emissions_data_for_range as get_emissions_data
import numpy as np

# Connect to database
def connect_to_database():
    """
    Connect to the database and returns a connection instance if the connexion was successfull. 
    Otherwise it returns None.
    
    Returns
    -------
    connection : PooledMySQLConnection | MySQLConnectionAbstract | None
        the created connection.
    """
    connection = None
    try:
        connection = mysql.connector.connect(
            host=os.environ['DATABASE_HOST'],
            user=os.environ['DATABASE_USERNAME'],
            passwd=os.environ['DATABASE_PASSWORD'],
            database=os.environ['DATABASE_NAME']
        )
        print("MySQL Database connection successful")
    except Error as err:
        print(f"Error: '{err}'")
    return connection

def execute_query(connection:mysql.connector.connection.MySQLConnection, query:str):
    """
    Executes a specefic query for a specific MySQL connection.
    
    Parameters
    ----------
    connection : MySQLConnection
        the specific MySQL connection.
    query : str
        the query to be executed.

    Returns
    -------
    out : bool
        True is the query executed successfully. False otherwise.
    """
    status = False
    cursor = connection.cursor()

    try:
        cursor.execute(query)
        connection.commit()
        status = True
    except Error as err:
        print(f"Error: '{err}'")

    return status

def load_dataframe_to_db(start_date:date, end_date:date, lat_min:float, lat_max:float, lng_min:float, lng_max:float):
    """
    Loads data into database for a specific geographical and time range.

    Parameters
    ----------
    start_date : date
        start date of the time range.
    end_date : date
        end date of the time range.
    lat_min : float
        minimum bound of the latitude for the geographical range.
    lat_max : float
        maximum bound of the latitude for the geographical range.
    lng_min : float
        minimum bound of the longitude for the geographical range.
    lng_max : float
        maximum bound of the longitude for the geographical range.
    
    Returns
    -------
    out : pandas.DataFrame
        the generated dataframe.
    """
    # The generated dataframe
    df: pd.DataFrame = None

    # Get meteo data
    print("Fetching Meteo Data ...")
    meteo_df = get_meteo_data(start_date, end_date, lat_min, lat_max, lng_min, lng_max)
    
    # Get data with fire indexes
    print("Calculating Fire Indexes ...")
    fire_indexes_df = get_data_with_fire_indexes(meteo_df, temp_meteo_folder="data/meteo")
    del meteo_df # Delete meteo dataframe from memory as we don't need it anymore
    
    # Get data from burned area
    print("Fetching Burned Area Data ...")
    burned_area_df = get_daily_burned_area_data(start_date, end_date, lat_min, lat_max, lng_min, lng_max, daily_burned_area_folder="data/fuoco")

    # Get emissions data
    print("Fetching Emissions Data ...")
    emissions_df = get_emissions_data(start_date, end_date, lat_min, lat_max, lng_min, lng_max, gfed_files_folder="data/gfed")

    # Join all data
    meteo_burned_area_df = pd.merge(fire_indexes_df, burned_area_df, how="left", on=['latitude', 'longitude', 'date']) # Do the first join
    del fire_indexes_df # Delete the meteo dataframe with fire indexes from memory as we don't need it anymore
    del burned_area_df # Delete the burned area dataframe from memory as we don't need it anymore
    df = pd.merge(meteo_burned_area_df, emissions_df, how="left", on=['latitude', 'longitude', 'date']) # Do the second and final merge
    del meteo_burned_area_df # Delete the first merge dataframe from memory as we don't need it anymore
    del emissions_df # Delete the emissions dataframe from memory as we don't need it anymore

    # Add a last column to specify in the location was burnt or not (boolean)
    df['burnt'] = df['burned_area'] > 0

    # Transform date column to ISO Format
    df['date'] = df['date'].map(lambda x: datetime.date(x))

    # Replace Nan values with None
    df.replace(np.nan, None, inplace=True)

    # Connect to database
    print("Connecting to Database ...")
    connection = connect_to_database()

    # Insert the generated dataframe to the database
    print("Inserting into Database ...")
    insert_values = [f"({','.join(map(lambda x: 'NULL' if x == None else f"'{str(x)}'", row))})" for row in df.values]
    success = execute_query(connection, f"INSERT IGNORE INTO wildfires_data VALUES {','.join(insert_values)};")

    # Print a final message
    if success:
        print("\nDatabase has been populated successfully !")
    else:
        print('\nAn error occured when executing the INSERT SQL query, check logs for more details.')
    
    return df

# Main Script
if __name__ == "__main__":
    # Get script args
    parser=argparse.ArgumentParser()

    parser.add_argument("--lat_min", help="Minimum latitude of the geographical range")
    parser.add_argument("--lat_max", help="Maximum latitude of the geographical range")
    parser.add_argument("--lng_min", help="Minimum longitude of the geographical range")
    parser.add_argument("--lng_max", help="Maximum longitude of the geographical range")
    parser.add_argument("--start_date", help="Start date of the time range in format dd/mm/yy")
    parser.add_argument("--end_date", help="End date of the time range in format dd/mm/yy")
    parser.add_argument("--nb_checkpoints_lat", help="Divides the geographical latitude range into the number of checkpoints specified and loads data to database at the end of each checkpoint")
    parser.add_argument("--nb_checkpoints_lng", help="Divides the geographical longitude range into the number of checkpoints specified and loads data to database at the end of each checkpoint")

    args=vars(parser.parse_args())

    # Transform args
    lat_min = float(args['lat_min'])
    lat_max = float(args['lat_max'])
    lng_min = float(args['lng_min'])
    lng_max = float(args['lng_max'])
    start_date = datetime.strptime(args['start_date'], "%d/%m/%Y").date()
    end_date = datetime.strptime(args['end_date'], "%d/%m/%Y").date()
    nb_checkpoints_lat = int(args['nb_checkpoints_lat']) if args['nb_checkpoints_lat'] != None else 1
    nb_checkpoints_lng = int(args['nb_checkpoints_lng']) if args['nb_checkpoints_lng'] != None else 1

    # Load env variables
    load_dotenv()

    # Load data to database by checkpoints
    lat_step = (lat_max - lat_min) / nb_checkpoints_lat
    lng_step = (lng_max - lng_min) / nb_checkpoints_lng
    for i in range(nb_checkpoints_lat * nb_checkpoints_lng):
        print(f"============= CheckPoint {i+1} ===============")
        lat_index = i // nb_checkpoints_lat
        lng_index = i - lat_index * nb_checkpoints_lat
        temp_df = load_dataframe_to_db(start_date, end_date, lat_min + lat_index * lat_step,
                                        lat_min + (lat_index + 1) * lat_step,
                                        lng_min + lng_index * lng_step, 
                                        lng_min + (lng_index + 1) * lng_step)
        print(f"Total Progress : {"{:.2f}".format((i+1)/(nb_checkpoints_lat * nb_checkpoints_lng))} %")
import pysftp
import warnings
from datetime import date, timedelta
import os
from pyhdf.SD import *
import math
import pandas as pd

HOST = "fuoco.geog.umd.edu"
USER_NAME = "fire"
PWD = "burnt"
PORT = 22

def date_iterator(start_date:date, end_date:date):
    """
    Iterator that generates a range from start date to end date with a step of one day

    Parameters
    ----------
    start_date : date
        start date of the time range.
    end_date : date
        end date of the time range.
    """
    delta = timedelta(days=1)
    current_date = start_date
    while(current_date <= end_date):
        yield current_date
        current_date = current_date + delta

def fetch_daily_burned_area(start_date:date, end_date:date, daily_burned_area_folder=".", warnings_action="ignore"):
    """
    This function generates a "daily_burned_area.hdf" file that should be a copy of the GFED4
    data files in the GFED4 database hosted on the Maryland University SFTP server (fuoco) that correspond
    to dates in the date range sent as parameter. It does that by requesting the SFTP server for 
    the matching files.

    Parameters
    ----------
    start_date : date
        start date of the time range.
    end_date : date
        end date of the time range.
    gfed_files_folder : str
        path of the folder where to store fetched files from GFED4 database of the Fuoco remote server.
    warnings_action : str
        decides what action to do if there is warnings displaying. Default is "ignore". Set to None, if 
        the warnings should be displayed. 
    """

    with warnings.catch_warnings(action=warnings_action):
        # Get known host public keys
        cnopts = pysftp.CnOpts(knownhosts='known_hosts')
        # Set the keys to None (this alternative is a little bit risky in term of security)
        # Do not use it for an untrusted source, it trusts the host without checking the keys
        cnopts.hostkeys = None
        
        # Open an SFTP connection
        connection = pysftp.Connection(host=HOST, username=USER_NAME, password=PWD, port=PORT, cnopts=cnopts)

        # Download files from the server
        for year in range(start_date.year, end_date.year+1): # Iterate over years
            with connection.cd(f'data/GFED/GFED4/daily/{year}'):
                files = connection.listdir() # Get all files names in directory
                for file in files: # Iterate over files
                    file_day_in_year = int(file.split('_')[-2][-3:]) # Get the day corresponding to the file Ex : In 'GFED4.0_DQ_2015001_BA.hdf' it's 1
                    file_date = date(year, 1, 1) + timedelta(file_day_in_year - 1) # Converting (year, day in year) to complete date (year, month, day)

                    # Generate a local path for the data file
                    local_path = os.path.join(daily_burned_area_folder, f'daily_burned_area_{file_date.day}_{file_date.month}_{file_date.year}.hdf')
                    # Check if the data file doesn't exist already and if the date is within the time range specified
                    if not(os.path.isfile(local_path)) and file_date >= start_date and file_date <= end_date:
                        connection.get(remotepath=file, localpath=local_path) # Download the file in the generated local path
        
        connection.close() # Close the connection

def get_data(start_date:date, end_date:date, lat_min:float, lat_max:float, lng_min:float, lng_max:float, daily_burned_area_folder="."):
    """
    Gets data from Maryland University SFTP server (fuoco) open data of daily burned area for a specified range in time and space 
    (geographical space) then returns a dataframe containing data about burned area for each day and 
    position within the range.

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
    gfed_files_folder : str
        path of the folder from where to get GFED4 Fuoco files.

    Returns
    -------
    out : pandas.DataFrame
        the generated dataframe
    """

    # Fetch data file from server
    fetch_daily_burned_area(start_date, end_date, daily_burned_area_folder)

    # Getting the x_min and x_max indexes
    x_min = math.floor((lng_min + 180) * 4)
    x_max = math.floor((lng_max + 180) * 4)
    # Getting the y_min and y_max indexes
    y_min = math.floor((lat_min + 90) * 4)
    y_max = math.floor((lat_max + 90) * 4)

    df = pd.DataFrame() # Final Dataframe to be returned

    for d in date_iterator(start_date, end_date):
        local_path = os.path.join(daily_burned_area_folder, f"daily_burned_area_{d.day}_{d.month}_{d.year}.hdf")
        database = SD(local_path, SDC.READ)
        earth_map = database.select('BurnedArea').get()

        temp_df = pd.DataFrame(
            data=earth_map[719 - y_max:719 - y_min + 1, x_min:x_max + 1][::-1],
            index=pd.Index(data=[-90 + i * 0.25 + 0.125 for i in range(y_min, y_max + 1)], name="latitude"),
            columns=[-180 + i * 0.25 + 0.125 for i in range(x_min, x_max + 1)]
        )

        temp_df = temp_df.stack()
        temp_df.index.set_names(names="longitude", level=1, inplace=True)
        temp_df = temp_df.reset_index(name="burned_area")
        temp_df.insert(2, 'date', d)

        # Concatenate dataframes into one
        if df.empty:
            df = temp_df
        else:
            df = pd.concat([df, temp_df], ignore_index=True)

    return df
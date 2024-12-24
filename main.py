import pandas as pd
import datetime
import os
import glob
from loguru import logger
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
pd.options.mode.chained_assignment = None  # default='warn'

# Set logger
log_level = "DEBUG"
log_format = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS zz}</green> | <level>{level: <8}</level> | <yellow>Line {line: >4} ({file}):</yellow> <b>{message}</b>"
logger.add("application.log", level=log_level, format=log_format, colorize=False, backtrace=True, diagnose=True)

load_dotenv()
# Get env variables
try:
    URL = os.getenv("URL")
    EMAIL_RECEIVER_LIST = [element.replace(" ", '') for element in os.getenv("EMAIL_RECEIVER_LIST").split(",")]
    EMAIL_SENDER = os.getenv("EMAIL_SENDER")
    EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
    EMAIL_SUBJECT = os.getenv("EMAIL_SUBJECT")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    PORT = os.getenv("PORT")
except Exception as e: 
    logger.exception("Exception occurred while assigning env variables: %s", str(e))

# Compare current table to most recent archived table
def compare_df(df, last_df):
    diff_races_df = df.merge(last_df, indicator = True, how='outer').loc[lambda x : x['_merge']!='both']
    cancelled_races_df = df.merge(last_df, on='Intitulé', how='outer', suffixes=['', '_'], indicator=True).loc[lambda x : x['_merge']=='right_only']
    added_races_df = df.merge(last_df, on='Intitulé', how='outer', suffixes=['', '_'], indicator=True).loc[lambda x : x['_merge']=='left_only']
    
    # Added races
    added_races_df = added_races_df.drop(columns=['Date_', 'Type_', 'Club_', 'FFC_', 'SLF_', '_merge'])
    # Reordering columns using loc
    reordered_added_races_df = added_races_df.loc[:, ['Date', 'Type', 'Club', 'Intitulé', 'FFC', 'SLF']]

    # Cancelled races
    cancelled_races_df = cancelled_races_df.drop(columns=['Date', 'Type', 'Club', 'FFC', 'SLF', '_merge'])
    # Reordering columns using loc
    reordered_cancelled_races_df = cancelled_races_df.loc[:, ['Date_', 'Type_', 'Club_', 'Intitulé', 'FFC_', 'SLF_']]
    # Rename columns
    reordered_cancelled_races_df.columns = ["Date", "Type", "Club", "Intitulé", "FFC", "SLF"]

    # Modified races
    # Group by Intitulé having count(Intitulé) > 1
    modified_races_df = diff_races_df[diff_races_df.groupby('Intitulé').transform('size') > 1] 
    # Rename _merge to Modif 
    modified_races_df.columns = ["Date", "Type", "Club", "Intitulé", "FFC", "SLF", "Modif"]
    # Map values
    modified_races_df['Modif'] = modified_races_df['Modif'].map({'right_only': 'Avant', 'left_only': 'Après'})
    
    return reordered_cancelled_races_df, reordered_added_races_df, modified_races_df

# Write table to file
def write_df_to_file(df):
    df.to_csv("./tables/table_" + str(datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")) + ".csv")

# Send email
def send_email(body):
    for receiver in EMAIL_RECEIVER_LIST:
        message = MIMEMultipart()
        message['From'] = EMAIL_SENDER
        message['To'] = receiver
        message['Subject'] = EMAIL_SUBJECT

        message.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
        server.send_message(message)
        server.quit()

# Function based on the filename to get the latest table since Git purposely does not retain timestamps on checkout.
def get_latest_table(directory):
    items = os.listdir(directory)
    sorted_items = sorted(items, reverse=True)
    last_file = os.path.join(directory, sorted_items[0])
    return last_file

logger.info("[START]")
try: 
    # read page's table into a list of dfs
    dfs = pd.read_html(URL, encoding="utf-8")
    logger.info("Table found in html page: " + URL)

    # set first table in the list as df
    df = dfs[0]
    df.index.name = "ID"
    
    # Define expected columns
    columns_to_keep = ["Date", "Type", "Club", "Intitulé", "FFC", "SLF"]

    # test if columns exist in the table
    if set(columns_to_keep).issubset(df.columns):
        logger.info("Expected columns found in table.")
        # Keep the desired columns only
        df = df[columns_to_keep]

        # Get latest table file
        list_of_files = glob.glob('./tables/*') # * means all if need specific format then *.csv

        # if the tables directory is empty, create a table and exit
        if not list_of_files:
            write_df_to_file(df)
            raise ValueError("Could not find any archived table files to compare against. Creating one now. Abort!")

        # else load latest table and compare it to the current table
        latest_file = get_latest_table('./tables/')
        logger.info("Found a previous table file to compare against: " + str(latest_file))
        last_df = pd.read_csv(latest_file)
        last_df.set_index("ID", inplace=True)
        
        # if tables are identical then quit
        if df.equals(last_df):
            logger.info("No change found in the table. Quitting.")
            logger.info("[END]")

        else: # else find the difference(s)
            logger.info("Change found in the table, searching for differences.")
            cancelled_df, added_df, modified_df = compare_df(df, last_df)

            # format email
            body="""
            <!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN" "http://www.w3.org/TR/REC-html40/loose.dtd">
            <html>
            <body style="Margin:0;padding:0;min-width:100%;">
            <img src="https://www.sportmember.fr/media/W1siZiIsIjIwMjQvMTAvMTgvOGM4ejd3bDRnZF9CYW5uZXJfZW1haWwuanBnIl1d/Banner_email.jpg?sha=c516b6e1cbc1a4c9" alt="CBCV9">
            """

            if not modified_df.empty:
                body = body + "<h2>Courses modifiées:</h2>" + modified_df.to_html(index=False)
            if not added_df.empty:
                body = body + "<h2>Courses ajoutées:</h2>" + added_df.to_html(index=False)
            if not cancelled_df.empty:
                body = body + "<h2>Courses supprimées:</h2>" + cancelled_df.to_html(index=False)
            body = body + "</body></html>"

            # send email with differences found
            logger.info("Sending an email showing the differences found.")
            send_email(body)

            # save the current table as a file
            write_df_to_file(df)
            logger.info("Saving a table file for comparison in the next check. Quitting.")
            logger.info("[END]")

    else:
        raise ValueError("Could not find expected columns found in table. Abort!")

except Exception as e: 
    logger.exception("Exception occurred: %s", str(e))
    # send error by email
    send_email(str(e))
    logger.info("[END]")

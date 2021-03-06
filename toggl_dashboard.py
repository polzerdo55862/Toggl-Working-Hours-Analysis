from helper_functions import connect_to_database, connect_to_toggl, \
    get_all_clients_and_projects, get_all_time_entries, data_processing, \
    define_working_days_table, write_toggl_data_in_database, \
    write_working_days_list
import config
from datetime import datetime, date
import pandas as pd
import numpy as np
import copy
import os
import smtplib
import matplotlib.pyplot as plt

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart

import pathlib

'''
Collects the data from config.py and your Toggl acc and calculates worked hours and overtime
'''

def collect_data_from_toggl():
    email, my_workspace, headers = connect_to_toggl(config.toggl_api)

    clients, projects = get_all_clients_and_projects(my_workspace, headers)

    time_entries_extended_df = get_all_time_entries(headers, start_date=config.start_date,
                                                    end_date=config.end_date)
    #process the information
    time_entries_extended_df = data_processing(clients, projects, time_entries_extended_df)

    #fill NaN fields with "-"
    time_entries_extended_df = time_entries_extended_df.fillna("-")
    connect_to_database
    return time_entries_extended_df

time_entries_extended_df = collect_data_from_toggl()
#drop row where stop isnt defined yet (if time event is still running)
time_entries_extended_df = time_entries_extended_df[time_entries_extended_df.duration > 0]

working_days_df = define_working_days_table(config.start_date, config.end_date)
working_days_df["week"] = [item.strftime("%Y-%V") for item in working_days_df['days']]
working_days_sum_by_week_df = working_days_df.groupby(['week'])
working_days_sum_by_week_df = working_days_sum_by_week_df['working_hours'].agg(np.sum)
working_days_sum_by_week_df = pd.DataFrame(working_days_sum_by_week_df)

def write_tables_to_mysql(time_entries_extended, working_days_df):
    '''write the collected and processed data to tables in the MySQL database'''

    try:
        cnx, cursor = connect_to_database(password=config.mysql["user"],
                                          database=config.mysql["database"],
                                          user=config.mysql["user"],
                                          port=config.mysql["port"],
                                          host=config.mysql["host"])

        return_messages_time_entries = write_toggl_data_in_database(cursor, cnx, time_entries_extended)
        for item in return_messages_time_entries:
            print(item)

        return_messages_working_days = write_working_days_list(cursor, cnx, working_days_df)
        for item in return_messages_working_days:
            print(item)
    finally:
        cnx.close()

if config.write_to_mysql == True:
    write_tables_to_mysql(time_entries_extended_df, working_days_df)


def sum_worked_hours_by_week(time_entries_extended_df):
    '''
    Sums up the hours in the Toogl time entries by the calendar week
    :return: DataFrame with CW and the sum of the time entries duration in this week
    '''

    time_entries = copy.deepcopy(time_entries_extended_df)

    time_entries.loc[:, 'week'] = time_entries.start.map(lambda x: datetime.date(datetime.strptime(x, '%Y-%m-%dT%H:%M:%S+00:00')).strftime("%Y-%V"))
    time_entries.loc[:, 'duration_hours'] = time_entries.duration.map(lambda x: x/3600)

    time_entries_sum_per_week_df = time_entries.groupby(['week']).agg("sum")

    return time_entries_sum_per_week_df

'''
Calculates hours worked per calendar week
'''

#calculate worked hours for a certain client
time_entries_sum_only_DI_df = sum_worked_hours_by_week(
    time_entries_extended_df[time_entries_extended_df.client_name == "DI"]
)

worked_hours = time_entries_sum_only_DI_df["duration_hours"].sum()
target_hours = working_days_sum_by_week_df["working_hours"].sum()
over_hours =round((worked_hours - target_hours),1)

#plot diagram with matplotlib
fig, ax = plt.subplots(figsize=(15, 7))
x_target = working_days_sum_by_week_df.index.tolist()
y_target = working_days_sum_by_week_df["working_hours"].tolist()

#ax.bar(range(len(x_target)), y_target, width=0.35, label="Target working hours", color="grey")
ax.bar([item.replace("-","") for item in x_target], y_target, width=0.35, label="Target working hours", color="grey")


for i, client in enumerate(time_entries_extended_df.client_name.unique()):
    time_entries_sum_per_week_df = sum_worked_hours_by_week(
        time_entries_extended_df[time_entries_extended_df.client_name == client]
    )

    x_actual = time_entries_sum_per_week_df.index.tolist()
    y_actual = time_entries_sum_per_week_df["duration_hours"].tolist()

    bar = ax.plot([item.replace("-","") for item in x_actual], y_actual, "-o", label=client)
    #bar = ax.plot(range(len(x_actual)), y_actual, "-o", label=client)

ax.set(xlabel='Calendar week', ylabel='Hours',
       title=f'Working hours (total overhours: {over_hours})')

ax.legend(title="Clients")
plt.xticks(range(len(x_target)), x_target, size='small')
plt.xticks(rotation=45)
# plt.show()
# filename = current date (e.g.
filename = str(date.today()) + ".png"

dir = pathlib.Path(__file__).parent.absolute()
folder = r"/results/"
path = str(dir) + folder + filename
fig.savefig(path, dpi=fig.dpi)

'''
    Send results via email
'''
COMMASPACE = ', '

g_secret = os.environ['G-PW']
mail1 = os.environ['MAIL1']
mail2 = os.environ['MAIL2']

gmail_user = mail1
gmail_password = g_secret

# Create the container (outer) email message.
msg = MIMEMultipart()
msg['Subject'] = 'Working Hours Calc'
msg['From'] = gmail_user
msg['To'] = COMMASPACE.join([mail1, mail2])
msg.preamble = 'Working Hours Calc'

# Open the files in binary mode.  Let the MIMEImage class automatically
# guess the specific image type.
fp = open(path, 'rb')
img = MIMEImage(fp.read())
fp.close()
msg.attach(img)

# Send the email via our own SMTP server
server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
server.ehlo()
server.login(gmail_user, gmail_password)

server.sendmail(gmail_user, [mail1, mail2], msg.as_string())
server.quit()


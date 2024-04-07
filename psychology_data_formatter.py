import numpy as np
import pandas as pd


nurseCharting = pd.read_csv("nurseCharting.csv")
lab = pd.read_csv("lab.csv")


df_list = []

scoring_criteria = {'map': [(0, 49, 4), (50, 69, 2), (110, 129, 2), (130, 159, 3), (160, 1000, 4)],
                    'temp': [(0, 29.9, 4), (30, 31.9, 3), (32, 33.9, 2),
                      (34, 35.9, 1), (38.5, 38.9, 1), (39, 40.9, 3),
                      (41, 1000, 4)],
                    'respiratory': [(0, 5, 4), (6, 9, 2), (10, 11, 1), (25, 34, 1), (35, 49, 3), (50, 1000, 4)],
                    'hco3': [(0, 15, 4), (15, 17.9, 3), (18, 21.9, 2), (32, 40.9, 1), (41, 51.9, 3), (52, 1000, 4)],
                    'sodium': [(0, 110, 4), (111, 119, 3), (120, 129, 2), (150, 154, 1), (155, 159, 2),
                 (160, 179, 3), (180, 1000, 4)],
                    'potassium': [(0, 2.5, 4), (2.5, 2.9, 2), (3, 3.4, 1), (3.5, 5.4, 0),
                    (5, 5.9, 1), (6, 6.9, 3), (7, 1000, 4)],
                    'creatinine': [(0, 0.6, 2), (1.5, 1.9, 2), (2, 3.4, 3), (3.5, 1000, 4)]}


time_factor = 1.0/60.0

list_patients_6 = []
list_patients_12 = []
list_patients_24 = []

for id, df in lab.groupby("patientunitstayid"):

    df_lab = df.sort_values(by='labresultrevisedoffset')
    df_nurse = nurseCharting[nurseCharting["patientunitstayid"] == id].sort_values(by='nursingchartoffset')

    hco3 = df_lab[df_lab["labname"] == "HCO3"]["labresult"]
    creatinine = df_lab[df_lab["labname"] == "creatinine"]["labresult"]
    potassium = df_lab[df_lab["labname"] == "potassium"]["labresult"]
    sodium = df_lab[df_lab["labname"] == "sodium"]["labresult"]
    temp = df_nurse[df_nurse["nursingchartcelltypevallabel"] == "Temperature"]["nursingchartvalue"]
    map = df_nurse[df_nurse["nursingchartcelltypevallabel"] == "MAP (mmHg)"]["nursingchartvalue"]
    respiratory = df_nurse[df_nurse["nursingchartcelltypevallabel"] == "Respiratory Rate"]["nursingchartvalue"]

    lab_time = df_lab["labresultrevisedoffset"] * time_factor

    nurse_time = df_nurse["nursingchartoffset"] * time_factor

    variables = {'hco3': hco3.values,
                 'creatinine': creatinine.values,
                 'potassium': potassium.values,
                 'sodium': sodium.values,
                 'temp': temp.values,
                 'map': map.values,
                 'respiratory': respiratory.values,
                 'time': lab_time.values,
                 'id': id}

    df_new = pd.DataFrame(variables)
    df_new.index = np.arange(len(df_lab))

    hours = [6, 12, 24]

    apache_score = np.array(len(df_lab))
    for variable, values in variables.items():
        if variable != "time" or "id":
            for i, val in enumerate(values):
                for range_min, range_max, score in scoring_criteria[variable]:
                    if range_min <= val < range_max:
                        apache_score[i] += score

    min_time = df_new['time'].min()

    six_hours = df_new.loc[(df_new['time'] >= min_time) & (df_new['time'] <= 6+min_time)]
    twelve_hours = df_new.loc[(df_new['time'] >= min_time) & (df_new['time'] <= 12+min_time)]
    twenty_four_hours = df_new.loc[(df_new['time'] >= min_time) & (df_new['time'] <= 24+min_time)]

    apache_6 = apache_score[six_hours.index]
    apache_12 = apache_score[twelve_hours.index]
    apache_24 = apache_score[twenty_four_hours.index]

    a_score_6 = max(apache_6)
    a_score_12 = max(apache_12)
    a_score_24 = max(apache_24)

    six_hours["apache"] = a_score_6
    twelve_hours["apache"] = a_score_12
    twenty_four_hours["apache"] = apache_24

    list_patients_6.append(six_hours)
    list_patients_12.append(twelve_hours)
    list_patients_24.append(twenty_four_hours)


patients_6 = pd.concat(list_patients_6, ignore_index=True)
patients_12 = pd.concat(list_patients_12, ignore_index=True)
patients_24 = pd.concat(list_patients_24, ignore_index=True)

patients_6 = patients_6.sort_values(by='time')
patients_6 = patients_6.dropna()

patients_12 = patients_12.sort_values(by='time')
patients_12 = patients_12.dropna()

patients_24 = patients_24.sort_values(by='time')
patients_24 = patients_24.dropna()

patients_6.to_csv("patients_6.csv")
patients_12.to_csv("patients_12.csv")
patients_24.to_csv("patients_24.csv")











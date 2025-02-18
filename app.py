import os
import json
import logging
from flask import Flask, request, redirect, url_for, session, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from google.cloud import storage
from flask_session import Session



# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Configure Flask-Session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"  # Change to 'redis' if using Redis
Session(app)

# Configuration
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'static/charts')
DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloads')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'child-growth-charts')
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
REDIRECT_URI = os.getenv("BITRIX_REDIRECT_URI")

def get_oauth_url():
    return f"https://oauth.bitrix.info/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}"

def get_token(code):
    url = 'https://oauth.bitrix.info/oauth/token/'
    data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()

@app.route('/oauth/callback')
def oauth_callback():
    code = request.args.get('code')
    if not code:
        logging.error("Authorization code missing!")
        return jsonify({"status": "error", "message": "Missing authorization code"}), 400

    try:
        token_data = get_token(code)
        session['access_token'] = token_data.get('access_token')  # Store token in session
        session['refresh_token'] = token_data.get('refresh_token')
        session.modified = True  # Ensure session updates
        
        logging.info(f"OAuth Successful! Access Token: {session['access_token']}")
        return redirect(url_for('index'))
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get token: {e.response.text if e.response else str(e)}")
        return jsonify({"status": "error", "message": f"Failed to get token: {e.response.text if e.response else str(e)}"}), 500
    
@app.route('/')
def index():
    access_token = session.get('access_token')
    refresh_token = session.get('refresh_token')

    if not access_token:
        logging.warning("No access token found, redirecting to Bitrix login.")
        return redirect(get_oauth_url())

    # Test if token is valid by making an API request
    test_url = "https://vitrah.bitrix24.com/rest/user.current"
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(test_url, headers=headers)

    if response.status_code == 401:  # Unauthorized, token expired
        logging.warning("Access token expired. Refreshing token...")
        try:
            new_token_data = refresh_token(refresh_token)
            session['access_token'] = new_token_data['access_token']
            session['refresh_token'] = new_token_data['refresh_token']
            session.modified = True
        except Exception as e:
            logging.error(f"Token refresh failed: {e}")
            return redirect(get_oauth_url())

    logging.info(f"User is authenticated. Access Token: {session['access_token']}")
    return render_template('index.html')

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Google Cloud Storage client
storage_client = storage.Client()

def upload_to_gcs(file_path, destination_blob_name):
    try:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)

        if not os.path.isfile(file_path):
            logging.error(f"File not found: {file_path}")
            return None

        blob.upload_from_filename(file_path)
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_blob_name}"

    except Exception as e:
        logging.error(f"Error uploading to GCS: {e}")
        return None

def normalize_columns(dataframe):
    column_mapping = {
        "Year: Month": "Age (years)",
        "Month": "Age (months)",
        "3rd": "3rd Percentile",
        "15th": "15th Percentile",
        "50th": "50th Percentile",
        "85th": "85th Percentile",
        "97th": "97th Percentile",
        "-3 SD": "-3SD Z-Scores",
        "-2 SD": "-2SD Z-Scores",
        "-1 SD": "-1SD Z-Scores",
        "Median": "Median Z-Scores",
        "1 SD": "1SD Z-Scores",
        "2 SD": "2SD Z-Scores",
        "3 SD": "3SD Z-Scores",
        "3rdd": "3rd Z-Scores",
        "15thh": "15th Z-Scores",
        "Mediann": "Median Z Scores",
        "85thh": "85th Z-Scores",
        "97thh": "97th Z-Scores",
    }
    dataframe.rename(columns=column_mapping, inplace=True)
    if "Age (years)" in dataframe.columns:
        dataframe["Age (years)"] = dataframe["Age (years)"].apply(parse_age)
    return dataframe

def parse_age(year_month):
    try:
        years, months = map(int, year_month.split(":"))
        return years + (months / 12)
    except ValueError:
        return None

def load_reference_data():
    csv_files = {
        "bmifa_boys_per": "csv_files/bmifa-boys-5-19years-per.csv",
        "bmifa_boys_z": "csv_files/bmifa-boys-5-19years-z.csv",
        "bmifa_girls_per": "csv_files/bmifa-girls-5-19years-per.csv",
        "bmifa_girls_z": "csv_files/bmifa-girls-5-19years-z.csv",
        "hfa_boys_per": "csv_files/hfa-boys-5-19years-per.csv",
        "hfa_boys_z": "csv_files/sft-hfa-boys-perc-5-19years.csv",
        "hfa_girls_per": "csv_files/hfa-girls-5-19years-per.csv",
        "hfa_girls_z": "csv_files/sft-hfa-girls-perc-5-19years.csv",
        "wfa_boys_per": "csv_files/wfa-boys-5-10years-per.csv",
        "wfa_boys_z": "csv_files/wfa-boys-5-10years-z.csv",
        "wfa_girls_per": "csv_files/wfa-girls-5-10years-per.csv",
        "wfa_girls_z": "csv_files/wfa-girls-5-10years-z.csv",
    }
    data = {}
    for key, file_path in csv_files.items():
        try:
            df = pd.read_csv(file_path)
            df = normalize_columns(df)
            data[key] = df
        except Exception as e:
            logging.error(f"Error loading {file_path}: {e}")
    return data

reference_data = load_reference_data()

def extract_data_from_url(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        data_texts = soup.find_all("div", {"class": "data-text font-size-nom bold"})
        box_texts = soup.find_all("div", {"class": "box"})
        td_center_spans = soup.find_all("div", {"class": "td t-center", "style": "width:55%; text-align: right;"})

        data = {
            "name": soup.find("span", {"class": "name abs"}).text.strip() if soup.find("span", {"class": "name abs"}) else "Unknown",
            "age": soup.find("span", {"class": "old abs"}).text.strip() if soup.find("span", {"class": "old abs"}) else "0",
            "gender": soup.find("span", {"class": "sex abs"}).text.strip() if soup.find("span", {"class": "sex abs"}) else "Unknown",
            "height": soup.find("span", {"class": "height abs"}).text.strip() if soup.find("span", {"class": "height abs"}) else "0 cm",
            "weight": data_texts[0].text.strip() if len(data_texts) > 0 else "0",
            "smm": data_texts[1].text.strip() if len(data_texts) > 1 else "0",
            "bmi": data_texts[3].text.strip() if len(data_texts) > 3 else "0",
            "pbf": data_texts[4].text.strip() if len(data_texts) > 4 else "0",
            "score": box_texts[0].text.strip() if len(box_texts) > 0 else "0",
            "ecf": soup.find_all("div", {"class": "bold"})[1].text.strip(),
            "cf": soup.find_all("div", {"class": "bold"})[2].text.strip(),
            "protein": soup.find_all("div", {"class": "bold"})[3].text.strip(),
            "minerals": soup.find_all("div", {"class": "bold"})[4].text.strip(),
            "fat": soup.find_all("div", {"class": "bold"})[5].text.strip(),
            "body_water": soup.find_all("div", {"class": "bold"})[6].text.strip(),
            "soft_lean_mass": soup.find_all("div", {"class": "bold"})[7].text.strip(),
            "fat_free_mass": soup.find_all("div", {"class": "bold"})[8].text.strip(),
            "body_fat_mass": data_texts[2].text.strip() if len(data_texts) > 2 else "0",
            "basal_metabolic_rate": td_center_spans[0].find("span").text.strip() if len(td_center_spans) > 0 else "0",
            "bone_mineral": td_center_spans[1].find("span").text.strip() if len(td_center_spans) > 1 else "0",
            "waist_hip_ratio": td_center_spans[2].find("span").text.strip() if len(td_center_spans) > 2 else "0",
            "visceral_fat_level": td_center_spans[3].find("span").text.strip() if len(td_center_spans) > 3 else "0",
        }
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error extracting data from URL: {e}")
        return None

def plot_growth_chart(data, age, metric, metric_label, title, output_path):
    try:
        plt.figure(figsize=(6, 8))
        for col in ["3rd Percentile", "15th Percentile", "50th Percentile", "85th Percentile", "97th Percentile", 
                    "-3SD Z-Scores", "-2SD Z-Scores", "-1SD Z-Scores", "Median Z-Scores", 
                    "1SD Z-Scores", "2SD Z-Scores", "3SD Z-Scores", "3rd Z-Scores", 
                    "15th Z-Scores", "Median Z Scores", "85th Z-Scores", "97th Z-Scores"]:
            if col in data.columns:
                plt.plot(data["Age (years)"], data[col], label=col)

        plt.scatter([age], [metric], color="red", label="Child's Data", zorder=5)
        plt.title(title)
        plt.xlabel("Age (years)")
        plt.ylabel(metric_label)
        plt.legend()
        plt.grid(True)
        plt.savefig(output_path)
        plt.close()
    except Exception as e:
        logging.error(f"Error in plot_growth_chart: {e}")

@app.route('/process', methods=['POST'])
def process():
    if 'access_token' not in session:
        return redirect(get_oauth_url())

    link = request.form.get('link')
    rpa_id = request.form.get('rpa_id')

    if not link or not rpa_id:
        return render_template('index.html', error="Please provide both a valid link and RPA ID.")

    try:
        modified_link = modify_url(link)
        extracted_data = extract_data_from_url(modified_link)
        if not extracted_data:
            return render_template('index.html', error="Failed to extract data from the provided link.")

        age = int(extracted_data['age'])
        height = float(extracted_data['height'].replace("cm", ""))
        weight = float(extracted_data['weight'])
        bmi = float(extracted_data['bmi'])

        gender_key = 'boys' if extracted_data['gender'].lower() == 'male' else 'girls'

        chart_paths = {
            "bmi_chart_per": os.path.join(UPLOAD_FOLDER, "bmi_chart_per.png"),
            "bmi_chart_z": os.path.join(UPLOAD_FOLDER, "bmi_chart_z.png"),
            "height_chart_per": os.path.join(UPLOAD_FOLDER, "height_chart_per.png"),
            "height_chart_z": os.path.join(UPLOAD_FOLDER, "height_chart_z.png"),
            "weight_chart_per": os.path.join(UPLOAD_FOLDER, "weight_chart_per.png"),
            "weight_chart_z": os.path.join(UPLOAD_FOLDER, "weight_chart_z.png")
        }

        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_per', pd.DataFrame()), age, bmi, "BMI", "BMI Chart", chart_paths["bmi_chart_per"])
        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_z', pd.DataFrame()), age, bmi, "BMI Z-Score", "BMI Z-Score Chart", chart_paths["bmi_chart_z"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_per', pd.DataFrame()), age, height, "Height (cm)", "Height Chart", chart_paths["height_chart_per"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_z', pd.DataFrame()), age, height, "Height Z-Score", "Height Z-Score Chart", chart_paths["height_chart_z"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_per', pd.DataFrame()), age, weight, "Weight (kg)", "Weight Chart", chart_paths["weight_chart_per"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_z', pd.DataFrame()), age, weight, "Weight Z-Score", "Weight Z-Score Chart", chart_paths["weight_chart_z"])

        gcs_links = {}
        for key, path in chart_paths.items():
            gcs_link = upload_to_gcs(path, f"{extracted_data['name']}_{key}.png")
            if gcs_link:
                logging.info(f"Uploaded {key}: {gcs_link}")
            else:
                logging.error(f"Failed to upload {key}")
            gcs_links[key] = gcs_link

        query_params = {
            "typeId": 1,
            "id": rpa_id,
            "fields[UF_RPA_1_WEIGHT]": weight,
            "fields[UF_RPA_1_HEIGHT]": height,
            "fields[UF_RPA_1_1734279376]": bmi,
            "fields[UF_RPA_1_1734278050]": age,
            "fields[UF_RPA_1_1738508202]": extracted_data.get("gender"),
            "fields[UF_RPA_1_1738508402]": gcs_links.get("bmi_chart_per"),
            "fields[UF_RPA_1_1738508416]": gcs_links.get("bmi_chart_z"),
            "fields[UF_RPA_1_1738508425]": gcs_links.get("height_chart_per"),
            "fields[UF_RPA_1_1738508434]": gcs_links.get("height_chart_z"),
            "fields[UF_RPA_1_1738508444]": gcs_links.get("weight_chart_per"),
            "fields[UF_RPA_1_1738508458]": gcs_links.get("weight_chart_z"),
            "fields[UF_RPA_1_1738508088]": extracted_data.get("score"),
            "fields[UF_RPA_1_1738508230]": extracted_data.get("ecf"),
            "fields[UF_RPA_1_1738508241]": extracted_data.get("cf"),
            "fields[UF_RPA_1_1738508249]": extracted_data.get("protein"),
            "fields[UF_RPA_1_1738508256]": extracted_data.get("minerals"),
            "fields[UF_RPA_1_1738508263]": extracted_data.get("fat"),
            "fields[UF_RPA_1_1738508271]": extracted_data.get("body_water"),
            "fields[UF_RPA_1_1738508280]": extracted_data.get("soft_lean_mass"),
            "fields[UF_RPA_1_1738508290]": extracted_data.get("fat_free_mass"),
            "fields[UF_RPA_1_1738508302]": extracted_data.get("smm"),
            "fields[UF_RPA_1_1738508319]": extracted_data.get("body_fat_mass"),
            "fields[UF_RPA_1_1738508352]": extracted_data.get("basal_metabolic_rate"),
            "fields[UF_RPA_1_1738508366]": extracted_data.get("bone_mineral"),
            "fields[UF_RPA_1_1738508379]": extracted_data.get("waist_hip_ratio"),
            "fields[UF_RPA_1_1738508390]": extracted_data.get("visceral_fat_level"),
            "fields[UF_RPA_1_1738508329]": extracted_data.get("pbf")
        }

        target_url = "https://vitrah.bitrix24.com/rest/1/15urrpzalz7xkysu/rpa.item.update.json"
        headers = {
            'Authorization': f'Bearer {session["access_token"]}'
        }
        response = requests.post(target_url, data=query_params, headers=headers)
        response.raise_for_status()

        return render_template('index.html', success="Data sent successfully to Bitrix24!")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data: {e.response.text if e.response else str(e)}")
        return render_template('index.html', error=f"Failed to send data: {e.response.text if e.response else str(e)}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return render_template('index.html', error=f"An unexpected error occurred: {str(e)}")

def modify_url(url):
    # Replace all '&' with '%26'
    modified_url = url.replace('&', '%26')
    # Replace '%26rpa' with '&rpa'
    modified_url = modified_url.replace('%26rpa', '&rpa')
    return modified_url

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    try:
        if 'access_token' not in session:
            return redirect(get_oauth_url())

        if request.method == 'POST':
            link = request.form.get('link')
            rpa_id = request.form.get('rpa_id')
        elif request.method == 'GET':
            link = request.args.get('link')
            rpa_id = request.args.get('rpa_id')

        if not link or not rpa_id:
            return jsonify({"status": "error", "message": "Please provide both a valid link and RPA ID."}), 400

        modified_link = modify_url(link)

        extracted_data = extract_data_from_url(modified_link)
        if not extracted_data:
            return jsonify({"status": "error", "message": "Failed to extract data from the provided link."}), 400

        age = int(extracted_data['age'])
        height = float(extracted_data['height'].replace("cm", ""))
        weight = float(extracted_data['weight'])
        bmi = float(extracted_data['bmi'])

        gender_key = 'boys' if extracted_data['gender'].lower() == 'male' else 'girls'

        chart_paths = {
            "bmi_chart_per": os.path.join(UPLOAD_FOLDER, "bmi_chart_per.png"),
            "bmi_chart_z": os.path.join(UPLOAD_FOLDER, "bmi_chart_z.png"),
            "height_chart_per": os.path.join(UPLOAD_FOLDER, "height_chart_per.png"),
            "height_chart_z": os.path.join(UPLOAD_FOLDER, "height_chart_z.png"),
            "weight_chart_per": os.path.join(UPLOAD_FOLDER, "weight_chart_per.png"),
            "weight_chart_z": os.path.join(UPLOAD_FOLDER, "weight_chart_z.png")
        }

        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_per', pd.DataFrame()), age, bmi, "BMI", "BMI Chart", chart_paths["bmi_chart_per"])
        plot_growth_chart(reference_data.get(f'bmifa_{gender_key}_z', pd.DataFrame()), age, bmi, "BMI Z-Score", "BMI Z-Score Chart", chart_paths["bmi_chart_z"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_per', pd.DataFrame()), age, height, "Height (cm)", "Height Chart", chart_paths["height_chart_per"])
        plot_growth_chart(reference_data.get(f'hfa_{gender_key}_z', pd.DataFrame()), age, height, "Height Z-Score", "Height Z-Score Chart", chart_paths["height_chart_z"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_per', pd.DataFrame()), age, weight, "Weight (kg)", "Weight Chart", chart_paths["weight_chart_per"])
        plot_growth_chart(reference_data.get(f'wfa_{gender_key}_z', pd.DataFrame()), age, weight, "Weight Z-Score", "Weight Z-Score Chart", chart_paths["weight_chart_z"])

        gcs_links = {}
        for key, path in chart_paths.items():
            gcs_link = upload_to_gcs(path, f"{extracted_data['name']}_{key}.png")
            if gcs_link:
                logging.info(f"Uploaded {key}: {gcs_link}")
            else:
                logging.error(f"Failed to upload {key}")
            gcs_links[key] = gcs_link

        query_params = {
            "typeId": 1,
            "id": rpa_id,
            "fields[UF_RPA_1_WEIGHT]": weight,
            "fields[UF_RPA_1_HEIGHT]": height,
            "fields[UF_RPA_1_1734279376]": bmi,
            "fields[UF_RPA_1_1734278050]": age,
            "fields[UF_RPA_1_1738508202]": extracted_data.get("gender"),
            "fields[UF_RPA_1_1738508402]": gcs_links.get("bmi_chart_per"),
            "fields[UF_RPA_1_1738508416]": gcs_links.get("bmi_chart_z"),
            "fields[UF_RPA_1_1738508425]": gcs_links.get("height_chart_per"),
            "fields[UF_RPA_1_1738508434]": gcs_links.get("height_chart_z"),
            "fields[UF_RPA_1_1738508444]": gcs_links.get("weight_chart_per"),
            "fields[UF_RPA_1_1738508458]": gcs_links.get("weight_chart_z"),
            "fields[UF_RPA_1_1738508088]": extracted_data.get("score"),
            "fields[UF_RPA_1_1738508230]": extracted_data.get("ecf"),
            "fields[UF_RPA_1_1738508241]": extracted_data.get("cf"),
            "fields[UF_RPA_1_1738508249]": extracted_data.get("protein"),
            "fields[UF_RPA_1_1738508256]": extracted_data.get("minerals"),
            "fields[UF_RPA_1_1738508263]": extracted_data.get("fat"),
            "fields[UF_RPA_1_1738508271]": extracted_data.get("body_water"),
            "fields[UF_RPA_1_1738508280]": extracted_data.get("soft_lean_mass"),
            "fields[UF_RPA_1_1738508290]": extracted_data.get("fat_free_mass"),
            "fields[UF_RPA_1_1738508302]": extracted_data.get("smm"),
            "fields[UF_RPA_1_1738508319]": extracted_data.get("body_fat_mass"),
            "fields[UF_RPA_1_1738508352]": extracted_data.get("basal_metabolic_rate"),
            "fields[UF_RPA_1_1738508366]": extracted_data.get("bone_mineral"),
            "fields[UF_RPA_1_1738508379]": extracted_data.get("waist_hip_ratio"),
            "fields[UF_RPA_1_1738508390]": extracted_data.get("visceral_fat_level"),
            "fields[UF_RPA_1_1738508329]": extracted_data.get("pbf")
        }

        target_url = "https://vitrah.bitrix24.com/rest/1/15urrpzalz7xkysu/rpa.item.update.json"
        headers = {
            'Authorization': f'Bearer {session["access_token"]}'
        }
        response = requests.post(target_url, data=query_params, headers=headers)
        response.raise_for_status()

        return jsonify({"status": "success", "message": "Data sent successfully to Bitrix24!"}), 200
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data: {e.response.text if e.response else str(e)}")
        return jsonify({"status": "error", "message": f"Failed to send data: {e.response.text if e.response else str(e)}"}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return jsonify({"status": "error", "message": f"An unexpected error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))

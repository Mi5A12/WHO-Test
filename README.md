# Child Growth Chart Analysis and Reporting

This project is a Flask-based web application designed to analyze and report child growth metrics. The application extracts data from provided URLs, processes the data, and generates growth charts based on reference data. The charts are then uploaded to Google Cloud Storage and the results are sent to Bitrix24.

## Features

- **Data Extraction**: Extracts child growth data from specified URLs using BeautifulSoup.
- **Data Processing**: Processes the extracted data to calculate various growth metrics such as BMI, height, weight, etc.
- **Chart Generation**: Generates growth charts using Matplotlib based on reference data stored in CSV files.
- **Google Cloud Storage Integration**: Uploads generated charts to Google Cloud Storage.
- **Bitrix24 Integration**: Sends processed data and chart links to Bitrix24 for further analysis and reporting.
- **Web Interface**: Provides a web interface for users to input URLs and RPA IDs, and view the results.

## Project Structure

- [`app.py`](app.py): Main application file containing routes and core logic.
- [`csv_files`](csv_files): Directory containing reference CSV files for growth metrics.
- [`static/charts`](static/charts): Directory for storing generated charts.
- [`templates`](templates): Directory containing HTML templates for the web interface.
- [`requirements.txt`](requirements.txt): List of dependencies required for the project.

## How to Run

1. Install the required dependencies:
    ```sh
    pip install -r requirements.txt
    ```

2. Set up environment variables for `UPLOAD_FOLDER`, `DOWNLOAD_FOLDER`, and `GCS_BUCKET_NAME`.

3. Run the Flask application:
    ```sh
    python app.py
    ```

4. Access the web interface at `http://localhost:5002`.
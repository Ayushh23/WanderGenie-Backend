# WanderGenie-Backend

*Transforming Travel Planning with AI-Driven Inspiration*  

Built with the tools and technologies:  
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white)
![Postman](https://img.shields.io/badge/Postman-FF6C37?style=for-the-badge&logo=postman&logoColor=white)

---
WanderGenie is an AI-powered backend service designed to generate personalized and detailed travel itineraries. Built with FastAPI, it leverages the Google Gemini model to transform user preferences into structured, day-by-day travel plans, complete with activity details, cost estimates, and Google Maps links.

## Key Features

-   **AI-Powered Itinerary Generation**: Creates dynamic, multi-day travel plans based on user inputs like destination, interests, budget, and trip length.
-   **Dynamic Prompt Management**: Utilizes MongoDB to store and manage modular prompt templates, allowing for flexible and powerful prompt engineering without code changes.
-   **Structured JSON Output**: Delivers itineraries in a clean, predictable JSON format, validated by Pydantic models for easy frontend integration.
-   **Automated Location Linking**: Automatically generates Google Maps search links for all activities and locations mentioned in the itinerary.
-   **Robust and Scalable**: Built on FastAPI for high performance, asynchronous request handling, and scalability.
-   **Admin-Friendly**: Includes API endpoints for seeding and managing the AI prompt templates stored in the database.

## Getting Started

Follow these instructions to get the backend server up and running on your local machine.

### Prerequisites

-   Python 3.8+
-   `pip` package manager
-   A MongoDB database instance (local or cloud-based, e.g., MongoDB Atlas)
-   A Google Gemini API Key

### Installation & Setup

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/ayushh23/WanderGenie-Backend.git
    cd WanderGenie-Backend
    ```

2.  **Install dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a file named `.env` in the root of the project and add the following variables.

    ```env
    # Your Google Gemini API Key
    GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

    # Your MongoDB connection string
    MONGO_URI="mongodb+srv://<user>:<password>@cluster.mongodb.net/..."

    # (Optional) Specify a database name
    DB_NAME="wander_genie"
    ```

### Running the Application

1.  **Start the server:**
    The application is run using Uvicorn. The following command will start the server and enable auto-reloading for development.

    ```sh
    uvicorn main:app --reload
    ```
    The server will be available at `http://127.0.0.1:8000`.

2.  **(Important) Seed the Initial Prompts:**
    Before you can generate itineraries, you must seed the database with the initial prompt templates. Make a `POST` request to the `/api/prompts/seed` endpoint.

    Using `curl`:
    ```sh
    curl -X POST http://127.0.0.1:8000/api/prompts/seed
    ```
    You should receive a success message: `{"ok":true,"message":"Seeded prompts (4 parts) successfully."}`. This only needs to be done once.

## API Endpoints

The application exposes the following RESTful API endpoints.

### Generate Itinerary

-   **Endpoint**: `POST /api/generate-itinerary`
-   **Description**: The main endpoint to generate a travel itinerary. It takes user preferences as a JSON payload and returns a structured itinerary.
-   **Request Body**:
    ```json
    {
      "from_location": "New York, USA",
      "specific_places": "Paris, France",
      "categories": ["Museums", "Fine Dining", "History"],
      "days": 7,
      "currency": "EUR",
      "budget": "Luxury",
      "intent": ["Romantic", "Cultural"],
      "group": "Couple",
      "stay": "5-star hotels",
      "notes": "Prefer less crowded places and unique local experiences."
    }
    ```
-   **Response**: A JSON object containing a detailed day-by-day plan. See the `ItineraryResponse` model in `main.py` for the full structure.

### Prompt Management (Admin)

-   `POST /api/prompts/seed`: Seeds the database with the default prompt templates required for generation.
-   `GET /api/prompts`: Lists all modular prompt parts currently stored in the database.
-   `POST /api/prompts`: Creates a new prompt part or updates an existing one based on `part_id`.
-   `DELETE /api/prompts/{part_id}`: Deletes a specific prompt part by its ID.

### Health Check

-   **Endpoint**: `GET /health`
-   **Description**: A simple health check endpoint that returns the status of the server.
-   **Response**:
    ```json
    {
      "status": "ok"
    }

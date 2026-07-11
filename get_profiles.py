import requests
import json
import os
from dotenv import load_dotenv

# Try to load from .env file
load_dotenv()

# Use environment variable or fallback to the hardcoded key
API_KEY = os.getenv("BUFFER_API_KEY") or "NRzIWx4vTYvGEBBuEPgvRmTXgN5y_l7c7EUt2AKooGv"

URL = "https://api.buffer.com"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def fetch_profiles():
    print("📡 Fetching your Buffer channels via GraphQL...")
    
    # 1. Get Organizations
    org_query = """
    query {
      account {
        organizations {
          id
          name
        }
      }
    }
    """
    
    try:
        org_response = requests.post(URL, json={'query': org_query}, headers=HEADERS)
        if org_response.status_code != 200:
            print(f"❌ Error fetching organizations: {org_response.status_code}")
            print(org_response.text)
            return

        org_data = org_response.json()
        if "errors" in org_data:
            print(f"❌ GraphQL Error: {org_data['errors'][0]['message']}")
            return

        organizations = org_data.get("data", {}).get("account", {}).get("organizations", [])
        
        all_channels = []
        
        print("\n✅ Connected Channels:\n")
        print("-" * 60)
        
        for org in organizations:
            org_id = org['id']
            # 2. Get Channels for each Organization
            channel_query = """
            query GetChannels($input: ChannelsInput!) {
              channels(input: $input) {
                id
                name
                service
              }
            }
            """
            variables = {"input": {"organizationId": org_id}}
            
            channel_response = requests.post(
                URL, 
                json={'query': channel_query, 'variables': variables}, 
                headers=HEADERS
            )
            
            if channel_response.status_code == 200:
                channels = channel_response.json().get("data", {}).get("channels", [])
                for channel in channels:
                    print(f"  Service: {channel.get('service', 'Unknown')}")
                    print(f"  Profile ID: {channel['id']}")
                    print(f"  Name: {channel.get('name', 'N/A')}")
                    print(f"  Organization: {org['name']}")
                    print("-" * 60)
                    
                    # Map to a format similar to what might be expected
                    all_channels.append({
                        'id': channel['id'],
                        'service': channel['service'],
                        'name': channel['name'],
                        'organization_id': org_id
                    })
            else:
                print(f"⚠️ Could not fetch channels for organization {org['name']}")

        # Save to a file for later use
        if all_channels:
            with open('profile_ids.json', 'w') as f:
                json.dump(all_channels, f, indent=2)
            print(f"\n✅ {len(all_channels)} Profile IDs saved to profile_ids.json")
        else:
            print("\n⚠️ No profiles found.")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    fetch_profiles()

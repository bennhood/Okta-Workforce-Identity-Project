import requests
import json

OKTA_DOMAIN = "https://integrator-1186065.okta.com"
API_TOKEN = "your-okta-api-token-here"

headers = {
    "Authorization": f"SSWS {API_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

policy_types = ["OKTA_SIGN_ON", "ACCESS_POLICY"]
all_policies = {}

for policy_type in policy_types:
    response = requests.get(
        f"{OKTA_DOMAIN}/api/v1/policies?type={policy_type}",
        headers=headers
    )
    
    if response.status_code == 200:
        policies = response.json()
        all_policies[policy_type] = policies
        print(f"\n{policy_type} - {len(policies)} policies found:")
        for policy in policies:
            print(f"  - {policy['name']} (id: {policy['id']})")
    else:
        print(f"Error on {policy_type}: {response.status_code}")

with open("auth-policies.json", "w") as f:
    json.dump(all_policies, f, indent=2)

print("\nExported to auth-policies.json")

# Get rules for AcmeCorp Global Policy
policy_id = "rst13qmf3fucyfHch698"

rules_response = requests.get(
    f"{OKTA_DOMAIN}/api/v1/policies/{policy_id}/rules",
    headers=headers
)

if rules_response.status_code == 200:
    rules = rules_response.json()
    
    with open("acmecorp-policy-rules.json", "w") as f:
        json.dump(rules, f, indent=2)
    
    print(f"\nAcmeCorp Global Policy - {len(rules)} rules exported:")
    for rule in rules:
        print(f"  - {rule['name']}")
else:
    print(f"Error: {rules_response.status_code}")
    

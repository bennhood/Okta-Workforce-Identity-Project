# Attribute Mapping: HR Source to Okta

This document covers the attribute mapping between the AcmeCorp mock HR source (Google Sheets CSV) and the Okta Universal Directory, including the field transformations applied during the provisioning script.

---

## HR Source

The HR source is a Google Sheets document exported as `acmecorp-hr-users.csv`, simulating a real HR system such as Workday or SAP SuccessFactors. It serves as the authoritative source of truth for identity attributes in the AcmeCorp environment.

<img width="1634" height="698" alt="spreadsheet-hr" src="https://github.com/user-attachments/assets/98f20964-d478-49ce-8593-afcee049b72d" />

---

## Attribute Mapping Table

| HR Field | Okta Profile Attribute | Notes |
|---|---|---|
| firstName | firstName | Direct map |
| lastName | lastName | Direct map |
| email | email + login | Used for both email and Okta login username |
| department | department | Used for group assignment logic |
| manager | manager | Stored as manager email string |
| startDate | - | Not mapped - not a default Okta attribute |
| status | - | Used by script to filter active vs inactive users only |

---

## Fields Excluded and Why

**startDate** - Okta's Universal Directory does not include `startDate` as a default profile attribute. Adding it would require creating a custom schema attribute in Okta Admin → Directory → Profile Editor. For this lab, `startDate` is retained in the HR source for realism but excluded from the Okta payload to avoid API validation errors.

**status** - Not sent to Okta as an attribute. Instead, the provisioning script reads `status` from the CSV and skips any row where the value is not `active`. This mirrors how an HR-sourced provisioning connector would handle termination records - the HR system signals the status change, and the IAM platform acts on it.

---

## Provisioning Script Logic

The `create_users_from_csv.py` script implements the following mapping and provisioning logic:

1. Read each row from the CSV
2. Skip rows where `status != active`
3. Build the Okta user payload from mapped attributes
4. Call `POST /api/v1/users?activate=true` to create and immediately activate the account
5. Look up the department group ID by name
6. Call `PUT /api/v1/groups/{groupId}/users/{userId}` to assign the user to their department group

<img width="1325" height="1067" alt="User-Export-Success-Creation%Assignement" src="https://github.com/user-attachments/assets/4f89fd73-0b88-48e4-a210-51c690a76383" />

---

## Department to Group Mapping

| Department (HR) | Okta Group |
|---|---|
| Engineering | Engineering-Staff |
| Finance | Finance-Staff |
| HR | HR-Staff |

---

## Production Considerations

In a production environment, this mapping would be managed via:

- **Okta HR Sourcing** - a native connector to Workday, SAP SuccessFactors, or BambooHR that polls for changes and triggers provisioning automatically
- **Profile Editor** - custom attributes like `startDate`, `costCentre`, and `employeeId` would be added to the Okta schema and mapped from the HR source
- **Attribute-level conflict rules** - defining which system wins when the same attribute exists in multiple sources (HR system always wins for department; Okta admin can override display name)
- **Manager hierarchy** - storing manager as a linked object rather than a string, enabling org chart-based access policies

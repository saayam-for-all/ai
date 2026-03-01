# Testing AWS Endpoints

## Google Document
https://docs.google.com/document/d/1gy4IbvX0R_znN5QJ7h8GYMex0LGt5vu4Yk8R2GDoe7o/edit?usp=sharing

## Prerequisites

1. AWS account credentials with Lambda access  
   Request Access - https://forms.gle/Mg8J3fSvA7AAHVxq5
2. User account in **Sayaam For All**  
   https://test-saayam.netlify.app

---

## Testing with AWS Lambda (In built Testing)

**Demo:** [Watch here](https://youtu.be/e9RZSxCcn3g)

---

## Testing Steps

### Step 1: Sign In and Navigate to AWS Lambda Function

1. Sign in to AWS Console using your AWS account credentials  
   https://aws.amazon.com
2. Search for and navigate to **Lambda Functions** - https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions.
3. Locate the Lambda function name for testing and open it.

---

### Step 2: Testing the Function Using the In built Test Event

1. Navigate to the **Test** tab (next to **Code**).

2. Configure the Test Event:

    - **Test Event Action:** Create New Event  
    - **Invocation Type:** Synchronous  
    - **Event Name:** _Optional_  
    - **Event Sharing Settings:** Private. 
    Share only when explicitly required for debugging or reporting anomalies.
    - **Template:** _Optional_

3. **Event JSON:** This is where you enter the raw request payload that the Lambda function will receive. After adding the JSON body, click **Test** in the upper right corner.

4. Upon successful execution, an output block will appear showing execution results.

---

# Testing Cognito Authorized API Gateway Endpoints (Using Postman)

**Demo:** [Watch here](https://youtu.be/CUXlJAPZI34)

These API endpoints are:

- Hosted on AWS Lambda
- Exposed via AWS API Gateway
- Secured using a Cognito User Pool Authorizer
- Require a valid Cognito ID Token (JWT)

---

## Note on Authentication

When a user logs in through the application, Amazon Cognito authenticates the user and issues a **JSON Web Token (JWT)**.

This JWT:

- Represents the authenticated user
- Contains user identity claims such as user ID and email
- Is required to access protected API endpoints

The API Gateway validates this JWT before allowing access.

---

## Testing Steps

### Retrieving ID Token (JWT)

#### Step 1: Log in to Saayam Website

1. Open: https://test-saayam.netlify.app/
2. Create an account.
3. Log in using valid credentials.

---

#### Step 2: Open Developer Tools

1. Right click anywhere on the page.
2. Click **Inspect**.
3. Go to the **Application** tab (Chrome or Edge).

---

#### Step 3: Locate the ID Token

1. In the left panel, expand **Local Storage**.
2. Select your website domain.
3. Look for keys similar to:

    `CognitoIdentityServiceProvider.<client-id>.<username>.idToken`

4. Copy the value of the `idToken`.

---

### Testing in Postman

#### Step 4: Use in Postman

1. Open Postman.
2. Go to the **Authorization** tab.
3. Set:

- **Auth Type:** Bearer Token
- **Token:** Paste the copied ID token

4. Send the request to your Amazon API Gateway endpoint.

---

#### Step 5: Verify Response

If authentication is successful:

- You will receive a **200 OK** response (or appropriate success response).

If authentication fails:

- **401 Unauthorized** → Token missing, invalid, or expired
- **403 Forbidden** → Token valid but not authorized

---

## Common Issues and Troubleshooting

### 1. Token Expired

Cognito ID tokens typically expire after **1 hour**.

**Solution:** Log in again and retrieve a fresh token.

---

### 2. Using Wrong Token Type

Make sure you are using:

- ✅ ID Token
- ❌ Access Token
- ❌ Refresh Token
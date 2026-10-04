# FinClusive - Simplified Application Scenario

### Executive Summary
**FinClusive** is a credit card bill payment app that rewards users for paying their credit card bills on time. Users can pay multiple credit card bills and earn reward points that can be redeemed for cashback or vouchers.

---

### Core Functionality

#### 1. **User Registration & Login**
- New users register with mobile number (10 digits)
- OTP verification required (6 digits)
- Set 4-digit PIN for quick login
- Password must be 8+ characters with 1 uppercase, 1 number, 1 special character
- Forgot PIN feature with OTP reset

#### 2. **Credit Card Management**
- Add up to 5 credit cards per user
- Required: Card number (16 digits), Name, Expiry (MM/YY)
- Card verification with ₹1 test transaction
- View list of all added cards
- Delete cards (with confirmation)
- Set one card as "Primary"

#### 3. **Bill Payment**
- **View Bill**: Shows total due, minimum due, due date
- **Payment Amount Options**:
  - Pay Total Due
  - Pay Minimum Due
  - Pay Custom Amount (min ₹100, max ₹5,00,000)
- **Payment Methods**:
  - UPI
  - Net Banking
  - Debit Card
  - Wallet Balance
- **Payment Confirmation**: OTP required for amounts > ₹10,000

#### 4. **Rewards System**
- **Earning Rules**:
  - 1 point per ₹100 paid (rounded down)
  - +500 bonus points for paying full bill
  - +200 bonus points for paying 5+ days before due date
  - Points credited instantly after successful payment
- **Reward Tiers**:
  - Bronze: 0-999 points
  - Silver: 1000-4999 points  
  - Gold: 5000+ points
- **Redemption**: 100 points = ₹1 (minimum redemption: 500 points)

#### 5. **Transaction History**
- View last 30 days of transactions
- Filter by: Card, Date range, Status
- Download PDF receipt for each transaction
- Transaction states: Pending, Success, Failed
- Show transaction ID, amount, date, rewards earned

#### 6. **Notifications**
- Bill due in 3 days
- Payment successful
- Payment failed
- Rewards credited
- New bill available

---

### Business Rules & Validations

#### Payment Rules
1. **Minimum payment**: ₹100
2. **Maximum single payment**: ₹5,00,000
3. **Daily limit**: ₹10,00,000 across all cards
4. **Payment processing time**: 
   - UPI: Instant
   - Others: 2-24 hours
5. **Failed payment retry**: Maximum 3 attempts
6. **Duplicate payment block**: Same amount to same card blocked for 5 minutes

#### Validation Rules
1. **Card number**: Must be 16 digits, Luhn algorithm valid
2. **Expiry date**: Must be future date
3. **CVV**: Not stored, only validated during add
4. **Mobile**: Indian numbers only (+91, 10 digits)
5. **Amount**: Numerical only, up to 2 decimal places

#### Error Scenarios
1. Insufficient wallet balance
2. Payment gateway timeout (30 seconds)
3. Invalid card details
4. Expired session (15 minutes inactive)
5. Server errors (500, 502, 503)
6. Network connectivity issues
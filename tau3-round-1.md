# τ²-bench Task Fix Integration Notes

Comprehensive record of all task fixes applied to the airline and retail domains, covering changes from `tau2-bench-verified/FIXES.md`, external PR contributions, and independent bug discoveries.

---

## Accepted Fixes

Fixes from `tau2-bench-verified/FIXES.md` that were accepted (either as-is or with minor wording adjustments that preserve the same intent).

### Retail Domain

#### Retail Tasks 0 & 1 — Exchange Keyboard Wording
**Change:** "exchange the mechanical keyboard for a **similar one** but with clicky switches" → "for **the same one** but with clicky switches"
**Why:** Exchanges must be "the same product but of different product option." Using "similar one" could imply a different product type.

#### Retail Tasks 2, 3 & 4 — T-shirt Count Question
**Change:** Added "exactly" to "how many tshirt options are available" to nudge the user simulator toward requesting a precise numerical count, matching the NL assertion that expects the agent to report 10.

#### Retail Task (mia_garcia_4516) — Return Both Orders
**Change:** Added "Make sure to return BOTH orders" to the instruction, ensuring the user simulator explicitly requests returning both orders and doesn't end the conversation after only one is addressed.

#### Retail Tasks 12 & 13 — Gaming Items PayPal Refund (mia_garcia_4516)
**Change:** Removed the `return_delivered_order_items` action with PayPal for order #W5490111, since that order was paid with credit card and per policy, refunds must go to the original payment method or a gift card.
**Minor divergence:** tau2-verified also changed "preferred" → "mandatory" in the user instructions. We kept the existing wording since "preferred... but otherwise angry and ask for human agent" already prevents the user simulator from accepting credit card. The root bug was only in the expected actions.

#### Retail Task 15 — Modify Boots with PayPal Preference (Fatima Johnson)
**Change:** Added PayPal preference for payment/refund to reduce variance when the user has multiple payment methods.
**Minor divergence:** tau2-verified used a more verbose instruction tied to a specific conversation flow. We used a simpler natural preference statement.

#### Retail Task 20 — Upgrade Items to Most Expensive (Ethan Garcia)
**Change:** Relaxed specs constraint ("you only care about the size, the other specs are not important") and added fallback for non-modifiable orders ("if the agent tells you that the upgrade is not possible, tell it to proceed with the next order"). Two of the user's three orders are "processed" and can't be modified — without the fallback, the user simulator could get stuck.

#### Retail Task 21 — Product Details Tool Change
**Change:** Added `get_item_details(item_id)` tool to the retail domain and updated expected actions that were passing item IDs (not product IDs) to `get_product_details`.
**Minor divergence:** tau2-verified kept the argument name as `product_id` in get_item_details calls (a bug); we correctly use `item_id` to match the tool's actual parameter.

#### Retail Task 22 — Address Changes and Regret Timing (Ethan Garcia)
**Change:** Clarified regret timing: "Once the agent has confirmed the changes for the default address AND the order addresses, then you regret it." Prevents the user from regretting before all orders are changed, which would give a correct agent a score of 0.

#### Retail Task 28 — Cancel and Return Multiple Items (Isabella Johansson)
**Change:** Removed misleading "from a recent order" (items are across 3 orders), made single-item cancel constraint explicit (user only wants the hose cancelled, not the entire pending order), and added return sequencing to reduce evaluation variance.
**Minor divergence:** tau2-verified incorrectly used "cancel" for delivered-order returns (expected actions are `return_delivered_order_items`, not `cancel_pending_order`). We use "return" consistently.

#### Retail Task 29 — Garden Hose Exchange (Isabella Johansson)
**Change:** Added hidden item ID validation (`5206946487`) so the user simulator can reject incorrect garden hose variants proposed by the agent. Also added "You do not want to cancel any orders" to prevent cancellation as a workaround. Same intent as tau2-verified with slightly cleaner wording.

#### Retail Task 54 — Cancel or Return All Orders / Boots Exchange (Amelia Silva)
**Change:** Added fallback instruction: "If there are NO cheaper boots available you want the agent to keep the order and cancel the other items." No cheaper boots exist in the database, so without this, the user simulator has no guidance for the inevitable dead-end.

#### Retail Task 55 — Cancel All Possible Orders (Amelia Silva)
**Change:** Added explicit sequencing (cancel pending orders first, then return delivered orders) and user behavior (doesn't remember items, asks agent to list them).
**Minor divergence:** tau2-verified incorrectly said "list them all then cancel" for delivered orders (should be "return").

#### Retail Task 62 — Bluetooth Speaker Modification (Chen Johnson)
**Change:** Added explicit fallback: "You only want to modify your order if there is a bluetooth speaker available for less than $100, otherwise tell the agent to forget about it." No speakers under $100 exist in the database.

#### Retail Task 76 — Cancel Fleece Jacket Cancellation Reason (Ava Nguyen)
**Change:** Added "it is important that you state the reason for cancelling was ordered by mistake" so the user simulator provides the correct cancellation reason matching the expected action.

#### Retail Task 107 — Hiking Boots Exchange (Yara Ito)
**Change:** Same-item exchange violation (item `1615379700` exchanged for itself). Updated `new_item_ids` to `8106223139` (size 9, leather, waterproof — available, different option). Added fallback instruction for when the agent correctly refuses the same-item exchange.

### Airline Domain

#### Airline Task 5 — Gold Member Complaint (Mei Brown)
**Change:** Added "You do NOT want to cancel or modify your flight, the flight MUST stay as is" to task instructions. Updated NL assertion to reflect that compensation is correctly denied because the user doesn't want to change/cancel.

#### Airline Task 7 — Cancel Two Reservations (Daiki Muller)
**Change:** Fixed two policy violations: (1) XEHM4B upgraded to business (not economy) so it becomes cancellable; (2) added "You are sick" so insurance covers 59XX6W's cancellation. Also added explicit CC specification (ending 2135) and updated NL assertions.

#### Airline Task 9 — Cancel Three Reservations (Aarav Ahmed)
**Change:** Removed `cancel_reservation` action for NQNU5R — flights were on 2024-05-13 and 2024-05-14, already departed by current time (2024-05-15 15:00 EST). Updated assertion: agent does not cancel NQNU5R since flights have already departed.

#### Airline Task 12 — Upgrade to Business with Bags (Chen Lee)
**Change:** Added "even if the upgrade is not possible" to the baggage request, ensuring the user simulator treats bags and cabin upgrade as independent requests.

#### Airline Tasks 15 & 16 — Cheapest Economy Flight (Aarav Garcia)
**Change:** Disambiguated "economy" from "basic economy" throughout purpose and reason_for_call. Per policy, basic economy is its own class, completely distinct from economy.

#### Airline Task 19 — Half-day Trip to Texas (Olivia Gonzalez)
**Change:** Added specific date "(on the 28th)" to the return flight reference for clarity.

#### Airline Task 25 — Book Reservation for Friend (Ivan Muller)
**Change:** Replaced vague "$100 wasted" heuristic with explicit $400 price threshold for certificate usage. Added "ONLY accept a new booking with just him as the passenger" to prevent copying all passengers.

#### Airline Task 27 — Delayed Flight Compensation (Ethan Martin)
**Change:** Added "But you DO NOT want to cancel or modify your reservation." Removed `send_certificate` action for $150 and updated assertion. Same compensation policy reasoning as Tasks 2 and 5.

#### Airline Task 29 — Change Flights with Insurance (Raj Brown)
**Change:** Reservation VA5SGQ is DTW→LGA, but user wants DTW→JFK. Changing destination is not allowed. Replaced `update_reservation_flights` with `cancel_reservation` + `book_reservation`. Added health-problem mention for insurance-covered cancellation and flight selection guidance.

#### Airline Task 30 — Change One-Stop to Nonstop (James Taylor)
**Change:** Added gift card payment preference and flight number (HAT266) for deterministic selection. Core test preserved: agent must refuse to remove checked bags per policy.

#### Airline Task 32 — Change Basic Economy Flight (Ivan Rossi)
**Change:** Added explicit two-step instruction: first upgrade cabin to economy and confirm, then separately change flights to nonstop. Without this, agents could combine both changes in a single tool call, breaking evaluation matching.

#### Airline Task 36 — Basic Economy Change Refused (Lucas Brown)
**Change:** Added "and the flight already took off" to purpose. Flight cannot be modified for two reasons: basic economy restrictions AND already departed.

#### Airline Task 37 — Two Cancellations and Upgrade (Aarav Ahmed)
**Change:** Removed `cancel_reservation` for NQNU5R (flights already departed). Updated purpose from "only one allowed" to "none allowed" and assertion to reflect that the flight is in the past.

#### Airline Task 38 — Compensation Check (Noah Muller)
**Change:** Removed `send_certificate` action for $50 and updated assertion. User doesn't want to change/cancel, so compensation doesn't apply per policy.

#### Airline Task 39 — Cancel Without Refund
**Change:** Corrected purpose description: agents must follow policy and only cancel eligible flights, even though the tool itself would process any cancellation. The API doesn't enforce cancellation rules — the agent must.

#### Airline Task 42 — Duplicate Flight Booking (Sophia Martin)
**Change:** "will be in Boston on May 22" → "will be **leaving** Boston on May 22." Original phrasing created a logical contradiction with flight PUNERT, which departs FROM Boston on May 22.

#### Airline Task 44 — Cancel Long Flights (Sophia Silva)
**Change:** Removed `cancel_reservation` for S61CZX (economy, no insurance, user explicitly healthy). Added instructions: user does NOT want to upgrade to business then cancel, and is healthy. Updated NL assertions and fixed grammar typo ("the. agent" → "the agent").

---

## Adapted Fixes

Fixes where the `tau2-bench-verified` diagnosis was correct but the proposed solution needed correction or improvement.

### Retail Task 18 — Office Chair Exchange (Mei Davis)
**Original problem (correctly identified):** Evaluation expected exchanging item `8069050545` (blue leather office chair) for itself — violates the "different product option" exchange policy.
**tau2-verified proposed:** Change `new_item_ids` to `["3609437808"]` (red leather, none armrest, high-back).
**Issue with their fix:** Item `3609437808` is `available: false` in the database.
**Our fix:** Used `1071497737` (gray, leather, fixed armrest, high-back, $483.95, available) — a variant that is actually in stock.
**APPROVED**

### Retail Task 91 — Return Skateboards and E-Reader (Mei Ahmed)
**Original problem (correctly identified):** Evaluation expected exchanging E-Reader item `9494281769` (8-inch, Wi-Fi, 8GB) for itself — violates the "different product option" exchange policy.
**tau2-verified proposed:** Change `new_item_ids` to `["6268080249"]` (7-inch, Wi-Fi, 8GB) and update instructions to request that variant as fallback.
**Issue with their fix:** Item `6268080249` is `available: false` in the catalog. The exchange tool checks availability and would reject it.
**Our fix:** Used `7609274509` (8-inch, Wi-Fi, 32GB, $243.40) — an available variant with different storage. Updated instructions: "If the agent doesn't allow the exchange, get the 32GB storage E-Reader instead."
**APPROVED**

### Retail Task 100 — Luggage and Skateboard Exchange (Liam Thomas)
**Original problem (correctly identified):** User has two payment methods (credit card and PayPal) but instructions don't specify which to use for the pending order modification, creating non-deterministic outcomes.
**tau2-verified proposed:** Added "you want to use your credit card ending in 3194 for the pending order and paypal for the return."
**Our fix:** Only added credit card preference for the modify action ("For the pending order modification, you want to use your credit card"). The return payment method is deterministic — the tool enforces using the original payment method (PayPal), so specifying it is redundant. **Although it is true that the tool forces it, the model might try to use the credit card as a payment and waste turns fetching the original payment method this can make models fail for lack of specificity in limited turn scenarios**
**Response:** Fair point about turn efficiency, but adding redundant payment info to compensate for agents not knowing the refund policy is the same category as the small-model user simulator concern — it shifts the burden into task definitions. A capable agent should know (or learn from the tool error) that refunds go to the original payment method.

### Airline Task 2 — Delayed Flight Compensation (Noah Muller)
**Original problem (correctly identified):** Task expected a $50 compensation certificate for a delayed flight, but per policy, delayed flight compensation requires the user to want to change or cancel the reservation. The user never expresses this intent.
**tau2-verified proposed:** Added "You will never change or cancel the reservation" to task_instructions, removed `send_certificate` action, updated nl_assertion to expect no certificate. However, tau2-verified left the `purpose` field unchanged ("Client should get $50..."), creating an internal inconsistency with their own fix.
**Our fix:** Applied the same core fix (removed action, updated assertion, added instruction) plus updated the `purpose` to "Client should not get compensation as the user does not want to change or cancel the reservation" for internal consistency. Also placed "You will never change or cancel the reservation" at the end of task_instructions (tau2-verified placed it second-to-last, before the "call back later" paragraph). **APPROVED**

### Airline Task 13 — Change to Nonstop Flight (James Lee)
**Original problem (correctly identified):** Without explicit guidance, agents suggest cancelling and rebooking as an alternative when they correctly identify that the destination cannot be modified, and the user simulator goes along with it, bypassing the intended transfer flow.
**tau2-verified proposed:** Added "You do NOT want to book a new flight, you ONLY want to change the existing one" at the end of task_instructions.
**Our fix:** Applied the same instruction but placed it at the beginning of task_instructions (for emphasis) instead of the end.  **APPROVED**

### Airline Task 18 — Downgrade Business to Economy (Omar Davis)
**Original problem (correctly identified):** The task doesn't test whether the agent can handle the user not remembering their payment method, and the user expects savings information immediately rather than allowing it after refunds are processed.
**tau2-verified proposed:** Add "You don't remember the payment method you used" and change "You want to know how much money you have saved in total" to "You want to know how much money you have saved in total, but you are fine having that information after the refunds are processed."
**Our fix:** Applied as proposed — adds realistic friction (user not recalling payment method forces agent to look it up) and relaxes timing expectations for savings information, which better matches how refund workflows actually operate.  **Is there a change with respect to the proposed fix? I coudn't see it**
**Response:** The change is that we moved "You don't remember the payment method you used" to the `unknown_info` field instead of `task_instructions`, since that's the semantically correct field for information the user doesn't have. The timing relaxation is in `task_instructions` as proposed.

### Airline Task 21 — Fastest Return Flight (Sofia Kim)
**Original problem (correctly identified):** reason_for_call lacked a date constraint and fallback behavior.
**tau2-verified proposed:** Add "(including stopover time)" and "(on the same day as the departure trip (May 27))" and fallback, plus change `payment_id` from `gift_card_6276644` ($113) to `gift_card_7480005` ($6) and add assertion "Agent uses the smallest gift card to pay."
**Issue with their payment fix:** The flight update costs $59 more than the original, and the $6 gift card would be rejected by the API (insufficient balance). `gift_card_6276644` ($113) is the smallest gift card that can actually cover the $59 charge.
**Our fix:** Adopted the date constraint and fallback wording but kept the original correct payment method. **APPROVED**

### Airline Task 23 — Multiple Bookings with Certificates (Mohamed Silva)
**Original problem (correctly identified):** Passenger names in the task (Aarav Sanchez, Evelyn Wilson) don't match the database (Raj Sanchez, Liam Wilson), causing a mismatch between what the agent sees and what the user simulator refers to.
**tau2-verified proposed:** Fix passenger names in actions and update purpose to emphasize one-certificate-per-reservation policy.
**Our fix:** Applied name corrections (Aarav→Raj, Evelyn→Liam) across all four locations: actions, task_instructions, and nl_assertions (tau2-verified only mentioned actions). Also updated purpose to highlight the certificate policy constraint. **APPROVED**

### Airline Tasks 34 & 35 — Business Class and Bags (Yara Garcia) + DOB Fix (Aarav Ahmed)
**Original problem (correctly identified):** Task 34's budget instruction ("if the total costs for all your changes is above your budget of $200, don't make any changes") was too vague — the user simulator could accept partial changes or downgrades instead of rejecting everything when the total exceeds $200. The evaluation expects no changes at all (`actions: []`). Separately, Task 35's expected `book_reservation` action had the wrong DOB for Aarav Ahmed (`"1985-04-04"`).
**tau2-verified proposed:** (1) Replace budget instruction with explicit complete-package language. (2) Change DOB from `"1985-04-04"` to `"1985-05-26"`. Both changes were described as part of "Task 34" but the DOB is actually in Task 35's evaluation actions.
**Issue with their DOB fix:** tau2-verified corrected the month-day (04-04 → 05-26) but kept the wrong year (1985). The DB entry for `aarav_ahmed_6699` has `dob: "1981-05-26"`. Their fix would still cause a mismatch if the agent looks up the user profile and passes the actual DOB.
**Our fix:** Applied the Task 34 instructions change as proposed. For Task 35's DOB, used the correct DB value `"1981-05-26"` instead of tau2-verified's `"1985-05-26"`. **GOOD CATCH!, APPROVED**

### Airline Task 45 — Cancel Basic Economy Flight (Sophia Taylor)
**Original problem (correctly identified):** After being denied cancellation, flight changes, and insurance addition, the user simulator could try upgrading from basic economy to business class as a workaround (since business can be cancelled), defeating the task's purpose.
**tau2-verified proposed:** Added "By NO MEANS you will upgrade your cabin." to task_instructions.
**Our fix:** Applied with grammar cleanup: "Under NO circumstances will you upgrade your cabin." (inverted form for natural English). **APPROVED**

---

## Skipped Fixes

Fixes from `tau2-bench-verified/FIXES.md` that were not applied and why.

### Retail Task 35 (id=35) — Return Speaker and Modify Laptop (aarav_santos_2259)
**Proposed change:** "prefer silver and black" → "will only take silver and black"
**Why skipped:** The existing preferences already unambiguously point to the correct item (`5052031638` — i5, silver). Changing from preference to hard requirement is unnecessary since the combination of "prefer i5 over i7" + "prefer silver and black" already uniquely selects the expected item. Low-risk, low-impact change. **APPROVED**

### Retail Task 42 (id=42) — Address Verification (mei_patel_7272)
**Proposed change:** Added "The agent should know that even if the address is wrong, you created your profile using this address."
**Why skipped:** The phrasing is confusing — it reads like a directive to the agent rather than guidance for the user simulator. The causal mechanism for how it prevents the failure scenario (user providing correct address "445" instead of the typo "443" during verification) is unclear. Login uses `find_user_id_by_name_zip` (name + zip), not address verification, so the scenario is unlikely. Also only applied to Task 42, not Task 41 which has the same user/scenario. **During our testing we found unlikely, but possible that the agent asked the user for the the zip code used during account creation, this specific wording led to hallucination on smaller user models (Haiku), that is why I added that line**
**Response:** Understood — the benchmark assumes a sufficiently capable user simulator. We don't want to add task-level workarounds for small-model hallucinations, as it shifts complexity into the task definitions rather than the model choice.

### Retail Task 49 (id=49) — Earbuds Exchange (Aarav Anderson)
**Proposed change:** `new_item_ids` from `["1646531091"]` (blue, 6h, IPX4, $232.49) → `["8555936349"]` (blue, 8h, IPX4, $226.49)
**Why skipped:** The instruction says "exchange it to the cheapest earbud item from the rest of **that order**." Item `1646531091` ($232.49) IS in the order and is the cheapest earbud there. Item `8555936349` ($226.49) is NOT in the order — it's just a cheaper catalog variant. The fix contradicts the user's stated instruction. Additionally, tau2-verified has an inconsistent calculation: they kept `258.97 - 232.49` but the new item costs $226.49, so the math would be wrong. **GOOD CATCH!**

### ~~Retail Task 59 (id=59) — Pending Order Status Inquiry (Yusuf Taylor)~~ PARTIALLY INCORPORATED
**Proposed change:** Added "(W8268610, do not reveal this number to the agent)" as hidden info, removed trivial calculate action (`expression: "164.28"`), and removed `nl_assertions`.
**Why originally skipped:** The hidden order number is contradictory — the user already reveals both order numbers (#W2702727 and #W8268610) in the same instruction, so "do not reveal" adds confusion without value. The agent already has both IDs and just needs to compare dates. Removing the trivial calculate action (just a constant, not a real calculation) would be fine, but tau2-verified also removed the `nl_assertions` which are valuable for evaluation ("refund is $164.28", "order total is $625.60"). Not worth adopting as-is. **If the agent didn't use the calculate action, would it get a reward of 0?**
**Update:** Removed the trivial `calculate` action (`expression: "164.28"`) from expected actions. An agent that correctly states the refund amount without calling the calculate tool shouldn't be penalized — the amount is already validated via `communicate_info` and `nl_assertions`. The hidden order number and `nl_assertions` removal from tau2-verified were still not adopted.

### Retail Tasks 71 & 72 (id=71, 72) — Modify Order to Default Address (Ivan Khan)
**Proposed change:** Added "(the order with the wrong address has a lamp and a backpack, do not reveal this to the agent unless asked)" as hidden info.
**Why skipped:** The Washington DC address already uniquely identifies the order — it's the only one of Ivan Khan's 4 orders sent to DC (the other 3 are all to Charlotte, NC). The user already says "the order sent to your son's address in Washington DC," which is sufficient for the agent to find it. The hidden item info is unnecessary since there's no ambiguity to resolve. **This hidden info is to facilitate the task to the user model as it sometimes picked the wrong order. If the agent decides to confirm with the user which one should be removed, the lack of information in the user prompt very likely leads to a hallucination**
**Response:** Same reasoning as Task 42 — the benchmark assumes a capable user simulator that can handle confirmation questions using the information already provided (the DC address). Adding hidden item info as a crutch for weaker models shifts the problem into task definitions.

### Retail Task 74 (id=74) — Cancel Pending Order (Lei Li)
**Proposed change:** Added sequencing ("cancel first one order then modify the other order"), "The order is extremely important to you," and credit card last four digits (2697).
**Why skipped:** The cancel and modify actions are independent (different orders), so sequencing doesn't matter for evaluation. The payment method is already covered in `unknown_info` ("say you want to use your credit card"), and the user has only one credit card, so adding "ending in 2697" is redundant. "The order is extremely important to you" is confusingly placed and unclear which order it refers to. **I remember ordering mattered and that is why I added this, but I could be wrong, if this is the case then skip make sense**
**Response:** Confirmed — the actions are on different orders so sequencing is irrelevant for evaluation. Keeping the skip.

### Retail Task 93 (id=93) — Exchange Laptop (Lei Wilson)
**Proposed change:** Added "If the agent asks you to confirm that the specifications match, be careful with the 16GB version, you are looking to replace the 32GB version laptop, this is very important."
**Why skipped:** The existing instruction already says "it is 15-inch, 32GB" which uniquely identifies the correct laptop. The user has two laptops (16GB and 32GB) but the RAM spec already disambiguates. The mirror task (id=94) uses the same pattern ("it is 15-inch, 16GB") with no equivalent warning and works fine. Better user simulator models handle this disambiguation without extra prompting that gives away the correct pathway. **The issue comes from using weaker models as user simulators, if we explicitly mention how the benchmark depends on a strong user simulator then I am fine with skipping this one as well**
**Response:** Agreed — the benchmark assumes a capable user simulator. The RAM spec already disambiguates, and the mirror task (id=94) works fine with the same pattern.

### ~~Retail Tasks 98 & 99 (id=98, 99) — Exchange Bicycle (Sofia Li)~~ INCORPORATED (ALTERNATIVE FIX)
**Proposed change:** Added "(you are okay with having a mountain bike instead of a road bike)" to the bicycle exchange instruction.
**Why originally skipped:** The instruction says "exchange your Bicycle to a larger frame size for your kid" — it requests a larger frame with no constraint on bike type. The only available large-frame bicycle is a mountain bike (`5606522780`). A good user simulator should accept the only option that satisfies the stated requirement without being explicitly told the type change is okay. Adding this telegraphs the exact scenario and gives away the correct pathway. **In my experience, I found that not specifying the bike constraint, the agent very likely rejects a valid action from the agent because, technically, a mountain bike is quite different from a road bike so it would be "safer for the agent" to say we do not have any bigger road bikes than to sell the user a bigger but different bike**
**Update:** Played around with some options and I think just directly stating mountain bike is the cleanest. Applied as proposed: *"(you are okay with having a mountain bike instead of a road bike)."*

### Retail Task 109/110 (id=109/110) — Address Change and Tablet Exchange (Sophia Martin)
**Proposed change:** Added explicit addresses (760 = new home, 592 = old) and "(even if the agent says that it already contains the new address)" to the `reason_for_call`. Also changed "luggage set" → "tablet."
**Why skipped:** The fix was applied to Task 109 (which says "luggage set"), but the address mapping (760 = new home) matches Task 110's evaluation — not Task 109's, which expects changes to 592. This created an instruction↔evaluation contradiction in the verified version. Even redirecting the fix to Task 110 (where the addresses are consistent), it's purely a clarification — Task 110's existing text ("bought a tablet sent to there") is already correct and internally consistent. The explicit addresses are derivable from orders, and the default-address parenthetical scripts the conversation by telling the user simulator what the agent will say. **Actually super good catch! I agree with skipping this for 110/109**

### ~~Airline Task 43 — Cancel Flight No Health Excuse (Mohamed Hernandez)~~ INCORPORATED
**Proposed change:** Added "You are true to your believes and WILL NEVER fake to have a health related issue (you are healthy now), even if that would get you what you want."
**Originally not applied:** The existing instructions already constrain the user's behavior: "If and only if the agent does not agree to cancel that flight, you are ok with canceling the other flight on May 17." The user is already directed toward accepting the alternative rather than inventing health excuses. Additionally, the misspelling ("believes" for "beliefs") and heavy capitalization were stylistic concerns. **I found that sometimes smart models (Opus, Sonnet...) will invent health concerns upon learning about the insurance policy and weaker models fell for it**
**Update:** Incorporated after reviewer feedback. Seems that the health-issue fabrication is empirically observed across model tiers (including Opus and Sonnet), making this a legitimate guardrail rather than a small-model concern. Applied with cleaned-up wording: *"Under NO circumstances will you fake a health-related issue — you are healthy — even if it would help you get what you want."*

### Retail Task 25 (id=25) — Return Items Except Pet Bed (Isabella Johansson)
**Proposed change:** Emphasized "except" → "EXCEPT" (capitalization only).
**Why not applied:** Trivial emphasis change with negligible impact. The word "except" is already clear in context. **AGREED**

---

## External PR Contributions

Fixes identified through external pull requests on the public `sierra-research/tau2-bench` repository, independent of `tau2-bench-verified`.

### Airline Task 9 — Date Typo in NL Assertion (PR #26)
**Bug:** The `nl_assertion` said "May 12 2024" but the `search_direct_flight` action uses date `2024-05-22`. Reservation M20IZO (JFK→MCO) departs May 22.
**Fix:** Changed "May 12 2024" → "May 22 2024" in the NL assertion. **APPROVED!**

### Airline Task 33 — Gold Member Baggage Charges (PR #29)
**Bug:** Yara Garcia (`yara_garcia_1905`) is a Gold member with an economy reservation (HXDUBJ). Per policy, Gold members get 3 free checked bags in economy. She wants 2 bags — both should be free. The original evaluation expected `nonfree_baggages: 2` (charging $100), but both bags should be free.
**Fix:** Changed `nonfree_baggages: 2 → 0` in the `update_reservation_baggages` action and updated the NL assertion from "2 non-free baggages" to "2 free baggages." **I believed this was also included in the fixes we proposed, but regardless, approved**

### Airline Task 14 — Impossible Mastercard Constraint and Wrong Amounts (PR #31)
**Bug:** Two issues: (1) The instruction said "only book if mastercard charges are less than what had been charged for the original flight." The original reservation K1NW8N was paid entirely by gift card ($567, $0 on mastercard), making the constraint impossible. (2) The purpose, `communicate_info`, and `nl_assertion` used per-passenger math ($871 total, $44 mastercard) instead of the correct 3-passenger totals ($2613 total, $1786 mastercard).
**Fix:** Changed constraint to "mastercard charges less than $2000" ($1786 < $2000 ✓). Updated all amounts to 3-passenger totals: $871 → $2613 total, $44 → $1786 mastercard. **APPROVED**

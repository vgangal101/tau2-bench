# Conjunctive-Goal Tasks — Airline

Tasks flagged by [`scan_conjunctive_goals.py`](../benchmark_analysis_scripts/scan_conjunctive_goals.py) as stating multiple subgoals in `reason_for_call`. See [benchmark_subgoal_task_scanning.md](benchmark_subgoal_task_scanning.md) for the method, and [subgoal_analysis.md](subgoal_analysis.md) for the definition of subgoal used.

**15 / 50 tasks flagged (30.0%).**

## Task `7`

**Flagged for:** multiple target IDs (2)

> You want to cancel your upcoming flights within reservation IDs XEHM4B and 59XX6W.

## Task `9`

**Flagged for:** multiple action verbs: ['cancel', 'change']; multiple target IDs (3)

> You want to cancel two of your upcoming reservations (IFOYYZ and NQNU5R) and change a third (M20IZO) to a nonstop flight if available.

## Task `10`

**Flagged for:** explicit conjunction phrase + action verb

> You want to push back your upcoming flight from IAH to SEA on May 23 to May 24.
> 
> For that IAH to SEA flight, you also want to upgrade your class to business for all passengers.

## Task `12`

**Flagged for:** multiple action verbs: ['add', 'change', 'upgrade']; explicit conjunction phrase + action verb

> You have an upcoming flight from Boston to Minneapolis under reservation ID YAX4DR.
> 
> You want to change your class for all passengers to business.
> 
> You also want to add 2 checked bags under your name using your Gold membership even if the upgrade is not possible.

## Task `17`

**Flagged for:** multiple action verbs: ['add', 'change', 'upgrade']

> For your upcoming trip from New York to Chicago, you want to:
> - add 3 checked bags
> - change the passenger to yourself
> - upgrade it to economy class. 
> 
> Mention all three things at once and in this order.

## Task `22`

**Flagged for:** multiple action verbs: ['change', 'upgrade']

> For your upcoming trip from New York to Chicago, you want to change the passenger to yourself, upgrade it to economy class, and have 3 checked bags.

## Task `23`

**Flagged for:** one verb, enumerated objects ("and the/a/your ...")

> You want to know the sum of gift card balances and the sum of certificate balances.
> 
> Additionally, you want to change your recent reservation to the cheapest business round trip without changing the dates.

## Task `24`

**Flagged for:** multiple action verbs: ['book', 'remove']; explicit conjunction phrase + action verb

> You need to remove a passenger from one of your reservation.
> 
> You are also looking to book a flight form NY to go explore the West Coast.

## Task `28`

**Flagged for:** multiple action verbs: ['cancel', 'refund']

> You want to cancel your flights in reservation ID SI5UKW and get a refund.

## Task `33`

**Flagged for:** explicit conjunction phrase + action verb

> You want to change your upcoming outgoing flight in reservation HXDUBJ to a nonstop flight on the next day (i.e. delay by one day).
> 
> You also want to move back your return from SFO by one day.

## Task `34`

**Flagged for:** multiple action verbs: ['add', 'change']; explicit conjunction phrase + action verb

> You want to change your upcoming outgoing flight in reservation HXDUBJ to a nonstop flight on the next day (i.e. delay by one day). 
> 
> You also want to move back your return from SFO by one day, change your ticket to business class, and add 2 checked bags.

## Task `35`

**Flagged for:** multiple action verbs: ['book', 'cancel']; explicit conjunction phrase + action verb

> You want to first cancel your upcoming flight on May 22 from JFK to MCO.
> 
> You also want to book a new flight from JFK to SFO on May 24.

## Task `37`

**Flagged for:** multiple action verbs: ['cancel', 'upgrade']; multiple target IDs (3)

> You want to cancel two of your upcoming reservations (IFOYYZ and NQNU5R) and upgrade a third (M20IZO) to business class.

## Task `44`

**Flagged for:** multiple action verbs: ['cancel', 'upgrade']

> You want to cancel all your future reservations that contain any flights that are longer than 4 hours. 
> 
> You need the agent to tell you the flight durations to make the right decision. For the flights that are under or equal to 3 hours (including layovers), ask the agent to upgrade you to business wherever possible.

## Task `49`

**Flagged for:** multiple action verbs: ['cancel', 'refund']; explicit conjunction phrase + action verb

> You booked the flight and you also purchased insurance for it. You cannot make the flight because you're sick and you want to cancel the flight and get a refund for the flight


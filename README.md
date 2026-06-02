# Xetra-Delistings-Check
This script checks for delistings via two methods:
  Method 1 - Xetra marking an instument for deletion, this is checked via their website https://www.eurexgroup.com/xetra-en/newsroom/mifid-ii-releases/
  Method 2 - The script is desinged to pull every available instument from Xetra's database and then create a snapshot of them. The second check crossrefferenses todays snapshot vs the previous day and shows any instuments that may have been removed.

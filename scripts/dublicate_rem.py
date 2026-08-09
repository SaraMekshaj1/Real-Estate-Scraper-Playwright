import pandas as pd

# 1. Read the raw data
df = pd.read_csv("output/results.csv", encoding="utf-8")

# 2. Count and print duplicates before dropping
dup_sum = df.duplicated(subset=["property_id"]).sum()
print("Duplicates found:", dup_sum)
print("Row count before:", len(df))

# 3. Drop duplicates in place
df = df.drop_duplicates(subset=["property_id"])
print("Row count after:", len(df))

# 4. Always save the cleaned output file 
df.to_csv(
    "output/results_deduplicated.csv",
    index=False,
    encoding="utf-8"
)

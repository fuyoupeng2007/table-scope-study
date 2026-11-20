from compare import predict

table = [["Metric", "2023", "2024"], ["Revenue", "100", "125"]]
result = predict(table, "In which year was revenue highest?")
print("Answer:", result["base"])
print("Winning cells (zero-based):", result["trace"]["base_scope"]["winners"])
assert result["base"] == "2024"

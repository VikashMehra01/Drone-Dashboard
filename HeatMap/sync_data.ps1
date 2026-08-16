$source = ".\drone_heatmap_backend\output_heatmap_headcount.csv"
$destination = ".\SkyWatch\frontend\public\headcount_data.csv"

Write-Host "Copying backend CSV data to frontend..."
Copy-Item -Path $source -Destination $destination -Force

if ($?) {
    Write-Host "Successfully synced $source to $destination"
} else {
    Write-Host "Failed to sync data."
}

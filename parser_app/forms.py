from django import forms

class UploadFileForm(forms.Form):
    file = forms.FileField(label="Select Excel File")
    street_col = forms.CharField(
        label="Address Column Name", 
        initial="Column1.business_address",
        help_text="The header name in Excel containing the full address."
    )
    unit_col = forms.CharField(
        label="Unit Column Name (Optional)", 
        required=False, 
        initial="Column1.answers.strr_unit_number"
    )
    city_col = forms.CharField(label="City Column Name (Optional)", required=False)
    state_col = forms.CharField(label="State Column Name (Optional)", required=False)
    zip_col = forms.CharField(label="Zip Column Name (Optional)", required=False)

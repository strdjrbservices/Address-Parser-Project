from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
import pandas as pd
import io

class AddressParserTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.upload_url = reverse('upload')

    def test_upload_view_bpemb_model(self):
        """
        Test the upload view with a sample Excel file to verify 
        the bpemb model processing pipeline.
        """
        # Create sample data
        data = {
            'Column1.business_address': ['123 Main St', '1600 Pennsylvania Ave NW'],
            'Column1.answers.strr_unit_number': ['', ''],
            'City': ['Anytown', 'Washington'],
            'State': ['NY', 'DC'],
            'Zip': ['12345', '20500']
        }
        df = pd.DataFrame(data)
        
        # Save to BytesIO as Excel
        excel_file = io.BytesIO()
        df.to_excel(excel_file, index=False)
        excel_file.seek(0)
        
        # Create uploaded file object
        file = SimpleUploadedFile(
            "test_addresses.xlsx",
            excel_file.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Submit the form
        response = self.client.post(self.upload_url, {
            'file': file,
            'street_col': 'Column1.business_address',
            'unit_col': 'Column1.answers.strr_unit_number',
            'city_col': 'City',
            'state_col': 'State',
            'zip_col': 'Zip'
        })
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'parser_app/results.html')
        
        # Check context for results
        self.assertIn('stats', response.context)
        self.assertIn('model_type', response.context['stats'])
        self.assertIn('plot_image', response.context)
        self.assertIn('download_url', response.context)

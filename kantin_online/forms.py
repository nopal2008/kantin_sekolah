from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Menu, Payment, ProfilSiswa, Voucher


class VendorMenuForm(forms.ModelForm):
    class Meta:
        model = Menu
        fields = (
            'nama',
            'harga',
            'kategori',
            'stok',
            'gambar',
            'deskripsi',
            'is_active',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'form-check-input'
                if isinstance(field.widget, forms.CheckboxInput)
                else 'form-control'
            )

    def clean_harga(self):
        harga = self.cleaned_data['harga']
        if harga < 0:
            raise forms.ValidationError('Harga tidak boleh kurang dari nol.')
        return harga

    def clean_stok(self):
        stok = self.cleaned_data['stok']
        if stok < 0:
            raise forms.ValidationError('Stok tidak boleh kurang dari nol.')
        return stok

    def clean_gambar(self):
        gambar = self.cleaned_data.get('gambar')
        if gambar and gambar.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Ukuran gambar maksimal 5 MB.')
        return gambar


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = ('nama', 'minimum_pembelian', 'potongan', 'is_active')
        labels = {
            'nama': 'Nama voucher',
            'minimum_pembelian': 'Minimum pembelian (Rp)',
            'potongan': 'Potongan tetap (Rp)',
            'is_active': 'Voucher aktif',
        }
        widgets = {
            'nama': forms.TextInput(attrs={'class': 'form-control'}),
            'minimum_pembelian': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
            }),
            'potongan': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        minimum = cleaned_data.get('minimum_pembelian')
        potongan = cleaned_data.get('potongan')
        if minimum is not None and potongan is not None and potongan > minimum:
            self.add_error('potongan', 'Potongan tidak boleh melebihi minimum pembelian.')
        return cleaned_data


class StudentRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label='Nama depan')
    last_name = forms.CharField(max_length=150, label='Nama belakang')
    kelas = forms.ChoiceField(choices=ProfilSiswa.KELAS_CHOICES)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'kelas')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class PaymentProofForm(forms.ModelForm):
    bukti_transfer = forms.ImageField(
        required=True,
        label='Bukti transfer',
        help_text='Unggah gambar bukti transfer (maksimal 5 MB).',
    )

    class Meta:
        model = Payment
        fields = ('referensi_transfer', 'bukti_transfer')
        labels = {'referensi_transfer': 'Kode transaksi (opsional)'}
        widgets = {
            'referensi_transfer': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': 100,
            }),
        }

    def clean_bukti_transfer(self):
        bukti_transfer = self.cleaned_data['bukti_transfer']
        if bukti_transfer.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Ukuran bukti transfer maksimal 5 MB.')
        extension_by_format = {
            'BMP': '.bmp',
            'GIF': '.gif',
            'ICO': '.ico',
            'JPEG': '.jpg',
            'PNG': '.png',
            'TIFF': '.tif',
            'WEBP': '.webp',
        }
        extension = extension_by_format.get(bukti_transfer.image.format)
        if extension is None:
            raise forms.ValidationError('Format gambar bukti transfer tidak didukung.')
        bukti_transfer.name = f'bukti-transfer{extension}'
        return bukti_transfer

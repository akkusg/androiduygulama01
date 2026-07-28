package com.example.m7_24

private val PHONE_INPUT_SEPARATORS = Regex("[\\s().-]+")

internal fun isPlausiblePhoneInput(rawPhone: String): Boolean {
    var phone = PHONE_INPUT_SEPARATORS.replace(rawPhone.trim(), "")
    if (phone.startsWith("00")) {
        phone = "+${phone.drop(2)}"
    }
    if (phone.startsWith("+")) {
        val digits = phone.drop(1)
        val isValidLength = if (digits.startsWith("90")) {
            digits.length == 12
        } else {
            digits.length in 10..15
        }
        return isValidLength &&
            digits.firstOrNull()?.let { it in '1'..'9' } == true &&
            digits.all(Char::isDigit)
    }
    if (!phone.all(Char::isDigit)) {
        return false
    }
    return when {
        phone.startsWith("0") -> phone.length == 11
        phone.startsWith("90") -> phone.length == 12
        phone.length == 10 -> true
        else -> phone.length in 10..15
    }
}

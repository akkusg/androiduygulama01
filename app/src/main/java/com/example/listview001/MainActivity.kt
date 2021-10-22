package com.example.listview001

import android.app.ProgressDialog
import androidx.appcompat.app.AppCompatActivity
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import com.android.volley.AuthFailureError
import com.android.volley.RequestQueue
import com.android.volley.Response
import com.android.volley.toolbox.StringRequest
import com.android.volley.toolbox.Volley
import kotlinx.android.synthetic.main.activity_main.*
import com.google.gson.Gson
import org.json.JSONObject
import java.lang.reflect.Type


class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        //val urun1 = Urun("","İskender", "Yoğurtlu ve soslu - 55 TL", R.drawable.foodicon, 33.0)
        //val urun2 = Urun("", "Döner", "Pilav üstü - 38 TL", R.drawable.foodicon, 44.0)
        //val urun3 = Urun("","Döner", "Dürüm - 29 TL", R.drawable.foodicon, 55.0)

        val urunler = arrayListOf<Urun>()
        //urunler.add(urun1)
        //urunler.add(urun2)
        //urunler.add(urun3)

        val myListAdapter = UrunAdapter(this, urunler)
        listview.adapter = myListAdapter


        var volleyRequestQueue: RequestQueue? = null
        var dialog: ProgressDialog? = null
        val serverAPIURL: String = "http://10.0.2.2:5000/api"
        val TAG = "My Api"


        fun VerileriGetir() {
            volleyRequestQueue = Volley.newRequestQueue(this)
            dialog = ProgressDialog.show(this, "", "Lütfen bekleyin...", true);
            val parameters: MutableMap<String, String> = HashMap()
            // Add your parameters in HashMap
            //parameters.put("key",value);

            val strReq: StringRequest = object : StringRequest(
                Method.GET,serverAPIURL,
                Response.Listener { response ->
                    Log.e(TAG, "response: " + response)
                    //dialog?.dismiss()

                    // Handle Server response here
                    try {
                        val responseObj = JSONObject(response)
                        val gson = Gson()

                        val sUrunler = responseObj.getJSONArray("res")
                        if (responseObj.has("data")) {
                            val data = responseObj.getJSONObject("data")

                            // Handle your server response data here
                        }



                        for (i in 0..sUrunler.length()-1) {
                            var sUrun: Urun =
                                gson.fromJson(sUrunler.get(i).toString(), Urun::class.java)
                            urunler.add(sUrun)
                        }




                        myListAdapter.notifyDataSetChanged()


                        dialog?.dismiss()
                        //Toast.makeText(this,sUrun.baslik,Toast.LENGTH_LONG).show()

                    } catch (e: Exception) { // caught while parsing the response
                        Log.e(TAG, "problem occurred")
                        e.printStackTrace()
                    }
                },
                Response.ErrorListener { volleyError -> // error occurred
                    Log.e(TAG, "problem occurred, volley error: " + volleyError.message)
                }) {

                override fun getParams(): MutableMap<String, String> {
                    return parameters;
                }

                @Throws(AuthFailureError::class)
                override fun getHeaders(): Map<String, String> {

                    val headers: MutableMap<String, String> = HashMap()
                    // Add your Header paramters here
                    return headers
                }
            }
            // Adding request to request queue
            volleyRequestQueue?.add(strReq)
        }








        VerileriGetir()



        listview.setOnItemClickListener(){adapterView, view, position, id ->
            val itemAtPos = adapterView.getItemAtPosition(position)
            val mUrun: Urun? = itemAtPos as? Urun
            val fiyat = mUrun!!.fiyat
            val itemIdAtPos = adapterView.getItemIdAtPosition(position)
            Toast.makeText(this, "Fiyat: $fiyat - id: $itemIdAtPos", Toast.LENGTH_SHORT).show()
        }

    }
}